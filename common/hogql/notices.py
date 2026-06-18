from dataclasses import dataclass


@dataclass(frozen=True)
class HogQLNotice(dict):
    message: str
    start: int | None = None
    end: int | None = None
    fix: str | None = None

    def __post_init__(self) -> None:
        dict.__init__(self, message=self.message, start=self.start, end=self.end, fix=self.fix)

    def model_dump(self) -> dict[str, str | int | None]:
        return {"message": self.message, "start": self.start, "end": self.end, "fix": self.fix}
