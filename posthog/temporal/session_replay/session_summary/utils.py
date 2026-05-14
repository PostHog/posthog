def format_seconds_as_mm_ss(seconds: float, *, include_ms: bool = False) -> str:
    """Format seconds as MM:SS, or with ``include_ms`` as MM:SS.nnn / H:MM:SS.nnn."""
    if include_ms:
        total_seconds = int(seconds)
        millis = int(round((seconds - total_seconds) * 1000))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def parse_str_timestamp_to_ms(timestamp_str: str) -> int:
    return parse_str_timestamp_to_s(timestamp_str) * 1000


def parse_str_timestamp_to_s(timestamp_str: str) -> int:
    parts = timestamp_str.split(":")
    if len(parts) == 2:
        # MM:SS format
        minutes, seconds = int(parts[0]), int(parts[1])
        return minutes * 60 + seconds
    elif len(parts) == 3:
        # HH:MM:SS format
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")
