import json
from typing import Optional, Dict, Any
from posthog.models.experiment import Experiment


def build_experiment_summary_prompt(experiment: Experiment, custom_prompt: Optional[str] = None) -> str:
    """
    Build a comprehensive prompt for the LLM based on experiment data and results.

    Args:
        experiment: The experiment object containing all experiment data
        custom_prompt: Optional custom prompt to append to the base prompt

    Returns:
        A formatted prompt string for the LLM
    """

    # Get experiment status and timing info
    status = _get_experiment_status(experiment)
    days_running = _get_days_running(experiment)
    days_remaining = _get_days_remaining(experiment)

    # Get variants from feature flag
    variants = [v["key"] for v in experiment.feature_flag.variants]

    # Build the base prompt
    prompt = f"""
You are an expert product analyst. Write a short, clear summary (2-4 sentences) of the current state of the experiment "{experiment.name}".
Provide a bit of analysis, not just a single line.

Experiment details:
- Name: {experiment.name}
- Status: {status}
- Days running: {days_running}
"""

    if days_remaining is not None:
        prompt += f"- Days remaining: {days_remaining}\n"

    prompt += f"- Variants: {', '.join(variants)}\n"

    # Add results if available
    if experiment.metrics:
        prompt += "- Metrics: Available\n"
    else:
        prompt += "- Metrics: No metrics configured\n"

    # Add experiment configuration details
    if experiment.description:
        prompt += f"- Description: {experiment.description}\n"

    if experiment.conclusion:
        prompt += f"- Conclusion: {experiment.conclusion}\n"
        if experiment.conclusion_comment:
            prompt += f"- Conclusion Comment: {experiment.conclusion_comment}\n"

    prompt += """
Instructions:
- If there is a significant winner, mention the variant, win probability, and what this means for the experiment.
- If not, mention how long the experiment has been running, how much time is left, and whether the results are trending toward significance or if more data is needed.
- Comment on the relative performance of the variants, even if not significant, and mention the credible intervals and p-value if relevant.
- Do NOT speculate or invent results that are not in the data.
- Write as a product analyst would, not as an AI. Use clear, professional language.

Examples:
- "After 14 days, the test variant is leading with a 95% probability of being the best, showing a 12% lift over control. This result is statistically significant and suggests the test variant is outperforming the baseline."
- "The experiment has been running for 8 days with no significant difference between variants. More data is needed to draw a conclusion."
- "Control and test variants are performing similarly so far, with the test variant showing a slight, but not significant, improvement. Credible intervals overlap and the p-value is above the significance threshold."
"""

    # Add custom prompt if provided
    if custom_prompt and custom_prompt != "Generate a simple summary of this experiment":
        prompt += f"\nAdditional context: {custom_prompt}"

    return prompt


def build_experiment_results_prompt(experiment: Experiment, results: Dict[str, Any], custom_prompt: Optional[str] = None) -> str:
    """
    Build a comprehensive prompt for the LLM based on experiment data and cached results.

    Args:
        experiment: The experiment object containing all experiment data
        results: Cached experiment results from the query runner
        custom_prompt: Optional custom prompt to append to the base prompt

    Returns:
        A formatted prompt string for the LLM
    """

    # Get experiment status and timing info
    status = _get_experiment_status(experiment)
    days_running = _get_days_running(experiment)
    days_remaining = _get_days_remaining(experiment)

    # Get variants from feature flag
    variants = [v["key"] for v in experiment.feature_flag.variants]

    # Build the base prompt
    prompt = f"""
You are an expert product analyst. Write a short, clear summary (2-4 sentences) of the current state of the experiment "{experiment.name}".
Provide a bit of analysis, not just a single line.

Experiment details:
- Name: {experiment.name}
- Status: {status}
- Days running: {days_running}
"""

    if days_remaining is not None:
        prompt += f"- Days remaining: {days_remaining}\n"

    prompt += f"- Variants: {', '.join(variants)}\n"

    # Add results if available
    if results:
        p_value = results.get('p_value')
        probability = results.get('probability', {})
        credible_intervals = results.get('credible_intervals', {})
        significant = results.get('significant', False)
        significance_code = results.get('significance_code')

        prompt += f"- P-value: {p_value if p_value is not None else 'N/A'}\n"
        prompt += "Results:\n"

        # Add variant results
        if results.get('variants'):
            for variant in results['variants']:
                variant_key = variant.get('key', 'unknown')
                count = variant.get('count', 0)
                exposure = variant.get('exposure', 0)
                credible_interval = credible_intervals.get(variant_key, ['N/A', 'N/A'])
                prob = probability.get(variant_key)

                # Format credible interval
                ci_lower = f"{credible_interval[0]:.3f}" if credible_interval[0] != 'N/A' else 'N/A'
                ci_upper = f"{credible_interval[1]:.3f}" if credible_interval[1] != 'N/A' else 'N/A'

                # Format probability
                prob_str = f"{prob * 100:.1f}%" if prob is not None else 'N/A'

                prompt += f"- {variant_key}: {count} conversions, {exposure} exposures, credible interval: [{ci_lower}, {ci_upper}], probability of being best: {prob_str}\n"

        # Add winner information if significant
        if significant and probability:
            winning_variant = max(probability.items(), key=lambda x: x[1])[0]
            win_prob = probability[winning_variant]
            prompt += f"- Winner: {winning_variant} (win probability: {win_prob * 100:.1f}%)\n"
        else:
            prompt += "- No statistically significant winner yet.\n"
    else:
        prompt += "- No results available yet.\n"

    prompt += """
Instructions:
- If there is a significant winner, mention the variant, win probability, and what this means for the experiment.
- If not, mention how long the experiment has been running, how much time is left, and whether the results are trending toward significance or if more data is needed.
- Comment on the relative performance of the variants, even if not significant, and mention the credible intervals and p-value if relevant.
- Do NOT speculate or invent results that are not in the data.
- Write as a product analyst would, not as an AI. Use clear, professional language.

Examples:
- "After 14 days, the test variant is leading with a 95% probability of being the best, showing a 12% lift over control. This result is statistically significant and suggests the test variant is outperforming the baseline."
- "The experiment has been running for 8 days with no significant difference between variants. More data is needed to draw a conclusion."
- "Control and test variants are performing similarly so far, with the test variant showing a slight, but not significant, improvement. Credible intervals overlap and the p-value is above the significance threshold."
"""

    # Add custom prompt if provided
    if custom_prompt and custom_prompt != "Generate a simple summary of this experiment":
        prompt += f"\nAdditional context: {custom_prompt}"

    return prompt


def _get_experiment_status(experiment: Experiment) -> str:
    """Get the current status of the experiment"""
    from django.utils import timezone

    if not experiment.start_date:
        return "Draft"
    elif experiment.end_date and timezone.now() > experiment.end_date:
        return "Completed"
    elif experiment.conclusion:
        return f"Completed ({experiment.conclusion})"
    else:
        return "Running"


def _get_days_running(experiment: Experiment) -> int:
    """Calculate how many days the experiment has been running"""
    from django.utils import timezone

    if not experiment.start_date:
        return 0
    end_date = experiment.end_date or timezone.now()
    return (end_date - experiment.start_date).days


def _get_days_remaining(experiment: Experiment) -> Optional[int]:
    """Calculate how many days are remaining in the experiment"""
    from django.utils import timezone

    if not experiment.start_date or not experiment.end_date:
        return None
    remaining = (experiment.end_date - timezone.now()).days
    return max(0, remaining) if remaining > 0 else None
