from datetime import datetime, timezone

from posthog.models.experiment import Experiment
from posthog.constants import (
    ExperimentFinishActionEmailValue,
    ExperimentFinishActionType,
    ExperimentFinishSendEmailTargetCriteria,
    ExperimentSignificanceCode,
)

from posthog.email import EmailMessage
from posthog.templatetags.posthog_filters import percentage


def _get_subject(experiment: Experiment, experiment_results: dict) -> str:
    significant = experiment_results.get("significant")

    if significant:
        return f"Your experiment - {experiment.name} was a success 🎉."

    return f"Your experiment - {experiment.name} finished, but... the results are not as expected 😔"


def _get_significance_message(experiment_results: dict) -> str:
    significance_code = experiment_results.get("significance_code")

    if significance_code == ExperimentSignificanceCode.SIGNIFICANT:
        return "We collected enough data and can conclude that your testing has led to a significant improvement!"

    if significance_code == ExperimentSignificanceCode.HIGH_LOSS:
        return f"We think this experiment leads to a high loss in conversion."

    if significance_code == ExperimentSignificanceCode.HIGH_P_VALUE:
        return "We're not confident in the results, due to the experiment not having a big impact on conversion. (The p value is greater than 0.05)."

    if significance_code == ExperimentSignificanceCode.LOW_WIN_PROBABILITY:
        return "We concluded that this experiment has a low win probability (The win probability of all test variants combined is less than 90%.)"

    if significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE:
        return "The experiment didn't have enough exposure to be conclusive. (We need at least 100 people per variant to declare significance.)"

    return ""


def _get_next_steps(experiment_results: dict) -> tuple[str, str]:
    significance_code = experiment_results.get("significance_code")

    title = ""
    message = ""

    if significance_code == ExperimentSignificanceCode.HIGH_LOSS:
        title = "We recommend you review your hypothesis"
        message = f"""
        It's great you chose to run this experiment first, so that you didn't ship
        an unfavorable change for the users.

        It could be that your hypothesis was not correct, and the change you made
        did not impact user behavior in the way you expected.
        Take this as a learning opportunity to gain deeper insights into your users.
        """

    if significance_code == ExperimentSignificanceCode.HIGH_P_VALUE:
        title = "We recommend you consider different scale of changes"
        message = f"""
        It's okay! This doesn't necessarily mean your test was a failure! It
        suggests that the results observed between the variants could be due to
        random chance, rather than the change you implemented.

        Consider smaller changes: If you made a large change, it could be
        that smaller aspects of the change had different impacts – some positive,
        some negative – leading to an overall insignificant result. Consider
        breaking down the change into smaller parts and testing these
        individually.

        Consider larger changes: Conversely, if your change was too subtle
        or minor, it may not have been enough to affect user behavior. In this
        case, consider making a more impactful change and then testing that.
        """

    if significance_code == ExperimentSignificanceCode.LOW_WIN_PROBABILITY:
        title = "We recommend you ignore the results"
        message = f"""
        The results of this experiment conclude that there isn't much difference with
        the new changes you made. It might be a good idea to ignore the results alltogether,
        and try again with a different hypothesis.
        """

    if significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE:
        title = "We recommend you gather more enough data"
        message = f"""
        If your sample size was too small, or your testing period was too short,
        you might need to extend the sample size or duration of your test to gather more data.
        """

    return title, message


def _get_email_recepients(experiment: Experiment, experiment_results: dict) -> list[str]:
    significant = experiment_results.get("significant")
    finish_actions = experiment.finish_actions or []

    email_action = list(filter(lambda x: x.get("action") == ExperimentFinishActionType.SEND_EMAIL, finish_actions))

    if not email_action:
        return []

    value: ExperimentFinishActionEmailValue = email_action[0].get("value", {})
    email_recepients = value.get(ExperimentFinishSendEmailTargetCriteria.ALL, [])

    if significant:
        email_recepients.extend(value.get(ExperimentFinishSendEmailTargetCriteria.SUCCESS, []))
    else:
        email_recepients.extend(value.get(ExperimentFinishSendEmailTargetCriteria.FAILURE, []))

    return email_recepients


def send_experiment_email(
    experiment: Experiment,
    results: dict,
) -> None:
    experiment_results = results.get("result", {})

    next_steps_title, next_steps_message = _get_next_steps(experiment_results)
    probability = experiment_results.get("probability", {})
    control_probability = probability.get("control", 0)

    message = EmailMessage(
        campaign_key=f"experiment_result_{experiment.pk}",
        subject=_get_subject(experiment, experiment_results),
        template_name="experiment_result",
        template_context={
            "experiment": experiment,
            "is_success": experiment_results.get("significant"),
            "experiment_ran_to": experiment.end_date or datetime.now(timezone.utc),
            "experiment_ran_from": experiment.start_date,
            "significance_message": _get_significance_message(experiment_results),
            "next_steps_title": next_steps_title,
            "next_steps_message": next_steps_message,
            "control_probability": percentage(control_probability),
            "test_probability": percentage(1 - control_probability),
        },
    )

    email_recepients = _get_email_recepients(experiment, experiment_results)

    for email_recepient in email_recepients:
        message.add_recipient(email=email_recepient)

    message.send()
