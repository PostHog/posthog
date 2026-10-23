class WidgetQueryError(Exception):
    """A widget query failure whose message is safe to show on the tile.

    `run_widgets` returns the message as the tile error and does not log it as an exception, because these
    are expected user-facing failures (no access, an invalid query), not server faults.
    """

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
