from typing import Literal

from langchain_core.prompts import PromptTemplate


def format_prompt_string(prompt: str, template_format: Literal["mustache", "f-string"] = "mustache", **kwargs) -> str:
    """
    Format a prompt template with dynamic values.

    Useful when tools need to dynamically inject content into their description or prompts
    based on runtime context (e.g., user permissions, team settings).

    Args:
        prompt: The prompt template string with variables to be replaced.
                Variables should be in mustache format {{{variable}}} or f-string format {variable}.
        template_format: The template format to use. Defaults to "mustache".
        **kwargs: Variables to inject into the template.

    Returns:
        The formatted prompt string with all variables replaced.

    Example:
        >>> prompt = "You have access to: {{features}}"
        >>> formatted = format_prompt_string(prompt, features="billing, search")
        >>> print(formatted)
        "You have access to: billing, search"
    """
    return (
        PromptTemplate.from_template(prompt, template_format=template_format)
        .format_prompt(**kwargs)
        .to_string()
        .strip()
    )
