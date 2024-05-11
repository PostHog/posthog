from django import template

from posthog.models.experiment import Experiment
from posthog.constants import (
    ExperimentFinishActionEmailValue,
    ExperimentFinishActionType,
    ExperimentFinishSendEmailType,
    ExperimentSignificanceCode,
)

from posthog.email import EmailMessage
from posthog.templatetags.posthog_filters import percentage

register = template.Library()


def _get_subject(experiment: Experiment, experiment_results):
    significant = experiment_results["significant"]

    if significant:
        return f"Your experiment {experiment.name} was a success 🎉."

    return f"Your experiment {experiment.name} finished, but... the results are not as expected 😔"


def _get_significance_message(experiment_results):
    significance_code = experiment_results["significance_code"]

    if significance_code == ExperimentSignificanceCode.SIGNIFICANT:
        return "We collected enough data and can conclude that your testing has led to a significant improvement!"

    if significance_code == ExperimentSignificanceCode.HIGH_LOSS:
        return f"""
        We think this experiment leads to a loss in conversion (current value is {experiment_results['expected_loss'] * 100:.2f}%).
        """

    if significance_code == ExperimentSignificanceCode.HIGH_P_VALUE:
        return "We're not confident in the results, due to the experiment not having a big impact on conversion. (The p value is greater than 0.05)."

    if significance_code == ExperimentSignificanceCode.LOW_WIN_PROBABILITY:
        return "We concluded that this experiment has a low win probability (The win probability of all test variants combined is less than 90%.)"

    if significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE:
        return "The experiment didn't have enough exposure to be conclusive. (We need at least 100 people per variant to declare significance.)"

    return ""


def _get_next_steps(experiment, experiment_results):
    significance_code = experiment_results["significance_code"]

    title = ""
    message = ""

    if significance_code == ExperimentSignificanceCode.HIGH_LOSS:
        title = "We recommend you review your hypothesis"
        message = f"""
        It's great you chose to run this experiment first, so that you didn't ship an unfavorable change for the users.

        It could be that your hypothesis was not correct, and the change you made did not impact user behavior in the way
        you expected. Take this as a learning opportunity to gain deeper insights into your users.
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
        If your sample size was too small,
        or your testing period was too short, you might need to extend the
        duration of your test to gather more data.
        """

    return title, message


def _get_email_recepients(experiment, experiment_results):
    significant = experiment_results["significant"]
    finish_actions = experiment.finish_actions

    email_action = next(filter(lambda x: x.get("action") == ExperimentFinishActionType.SEND_EMAIL, finish_actions))

    value: ExperimentFinishActionEmailValue = email_action.get("value")
    email_recepients = value.get(ExperimentFinishSendEmailType.ALL) or []

    if significant:
        email_recepients.extend(value.get(ExperimentFinishSendEmailType.SUCCESS) or [])
    else:
        email_recepients.extend(value.get(ExperimentFinishSendEmailType.FAILURE) or [])

    return email_recepients


@register.filter
def send_experiment_email(
    experiment: Experiment,
    results: dict,
) -> None:
    experiment_results = results["result"]
    filters = experiment_results["filters"]

    next_steps_title, next_steps_message = _get_next_steps(experiment, experiment_results)

    message = EmailMessage(
        campaign_key=f"experiment_result_{experiment.pk}",
        subject=_get_subject(experiment, experiment_results),
        template_name="experiment_result",
        template_context={
            "experiment": experiment,
            "experiment_ran_from": filters.get("date_from"),
            "experiment_ran_to": filters.get("date_to"),
            "significance_message": _get_significance_message(experiment_results),
            "is_success": experiment_results["significant"],
            "next_steps_title": next_steps_title,
            "next_steps_message": next_steps_message,
            "control_probability": percentage(experiment_results["probability"].get("control")),
            "test_probability": percentage(1 - experiment_results["probability"].get("control")),
        },
    )

    email_recepients = _get_email_recepients(experiment, experiment_results)

    for email_recepient in email_recepients:
        message.add_recipient(email=email_recepient)

    message.send()
