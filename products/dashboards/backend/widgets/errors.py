class WidgetQueryError(Exception):
    """A widget query failure whose message is safe to show on the tile.

    `run_widgets` returns the message as the tile error and does not log it as an exception. Set `operational`
    for failures on our side (a timeout, a memory limit, no free query slot): the delivery SLO counts those
    as failures, while a viewer without access or an invalid query is not a delivery failure.
    """

    def __init__(self, user_message: str, *, operational: bool = False) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.operational = operational
