def compressed_memory_parser(memory: str) -> str:
    """
    Remove newlines between paragraphs.
    """
    return memory.replace("\n\n", "\n")
