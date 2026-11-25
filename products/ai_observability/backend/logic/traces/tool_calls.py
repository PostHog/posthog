def called_tool_names(event: str, tools_called: object) -> tuple[str, ...]:
    if event != "$ai_generation" or not isinstance(tools_called, str):
        return ()
    return tuple(name for name in (part.strip() for part in tools_called.split(",")) if name)
