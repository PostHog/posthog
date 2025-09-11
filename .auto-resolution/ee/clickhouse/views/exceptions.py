class TriggerGroupIdentifyException(Exception):
    def __init__(self, exception_data: dict, status_code: int):
        self.exception_data = exception_data
        self.status_code = status_code
