class GenerationCanceled(Exception):
    """Raised when generation is canceled."""

    pass


class HelpRequested(Exception):
    """Raised when a tool requests help from the user."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
