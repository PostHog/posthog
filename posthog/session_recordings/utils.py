def clean_prompt_whitespace(prompt: str) -> str:
    """
    Cleans unnecessary whitespace from prompts while preserving single spaces between words.
    Args:
        prompt: The input string to clean
    Returns:
        String with normalized whitespace - single spaces between words, no leading/trailing whitespace
    """
    # Replace multiple spaces with single space and strip leading/trailing whitespace
    return " ".join(prompt.split())
