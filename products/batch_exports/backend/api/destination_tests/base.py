import abc
import enum
import dataclasses
import collections.abc

from asgiref.sync import async_to_sync


class Status(enum.StrEnum):
    PASSED = "Passed"
    FAILED = "Failed"


DestinationTestStepResultDict = dict[str, str | None]


@dataclasses.dataclass
class DestinationTestStepResult:
    """The result of a test step.

    Attributes:
        status: Whether the test passed or failed.
        message: An optional message, only included on failure, describing the
            potential cause for the `status`.
    """

    status: Status
    message: str | None = None

    def as_dict(self) -> DestinationTestStepResultDict:
        """Serialize this as a dictionary."""
        return {
            "status": str(self.status),
            "message": self.message,
        }


DestinationTestStepDict = dict[str, str | DestinationTestStepResultDict | None]


class DestinationTestStep:
    """A single step in a destination test.

    Attributes:
        name: A short (ideally) string used to identify this step.
        description: A longer string with more details about this step.
        result: After running this test step, the result will be populated.
    """

    name: str = NotImplemented
    description: str = NotImplemented

    def __init__(self) -> None:
        self.result: DestinationTestStepResult | None = None

    @abc.abstractmethod
    def _is_configured(self) -> bool:
        """Internal method to verify this test step is configured.

        Subclasses should override this method and implement their concrete steps
        to ensure we are configured correctly.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def _run_step(self) -> DestinationTestStepResult:
        """Internal method to run this test step.

        Subclasses should override this method and implement their concrete running
        operations.
        """
        raise NotImplementedError

    async def run(self) -> DestinationTestStepResult:
        """Run this test step."""
        if not self._is_configured():
            return DestinationTestStepResult(
                status=Status.FAILED,
                message="The test step cannot run as it's not configured.",
            )

        try:
            result = await self._run_step()
        except Exception as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"The test step failed with an unknown error: {err}.",
            )
        return result

    def as_dict(self) -> DestinationTestStepDict:
        """Serialize this as a dictionary."""
        base: dict[str, str | DestinationTestStepResultDict | None] = {
            "name": self.name,
            "description": self.description,
        }
        if self.result:
            base["result"] = self.result.as_dict()
        else:
            base["result"] = None
        return base


class DestinationTest:
    """Interface representing a test executed for a particular destination.

    A test is composed of multiple test steps organized in a linear hierarchy.
    This is used to represent that a parent test step should pass before allowing
    the next test steps (its children) to run. As a concrete example, if we have
    a test to check whether we can connect to a database, and a second test step
    to check whether we can create a table, it makes no sense to run the second
    test step if the first one fails. Future revisions of this interface could
    expand the hierarchy to allow for multiple paths (a tree), but for now a simple
    list is sufficient.

    Attributes:
        steps: A property returning a sequence of steps to run.
    """

    @abc.abstractmethod
    def configure(self, **kwargs):
        """Method to configure a concrete test.

        By "configure" I mean setting any attributes required to initialize and/or
        run test steps.

        Subclasses should override this to set any attributes. This decoupling of
        configuration from initialization allows us to serialize a `DestinationTest`
        without needing to configure it.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Property returning a sequence of steps to run.

        Subclasses should override this with their required test steps.
        """
        raise NotImplementedError

    def run_step(self, step: int) -> DestinationTestStep:
        """Run the test step at index `step`."""
        test_step = self.steps[step]
        step_result = async_to_sync(test_step.run)()

        test_step.result = step_result
        return test_step

    def as_dict(self) -> dict[str, list[DestinationTestStepDict]]:
        """Serialize this as a dictionary."""
        return {"steps": [step.as_dict() for step in self.steps]}
