import asyncio
import collections.abc

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)


def try_load_private_key(
    private_key: str | None = None, private_key_passphrase: str | None = None
) -> tuple[bytes | None, DestinationTestStepResult | None]:
    """Attempt to load a private key, return a failed result if an error occurs."""
    from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
        InvalidPrivateKeyError,
        load_private_key,
    )

    if private_key is None:
        return (None, None)

    try:
        private_key_bytes = load_private_key(private_key, private_key_passphrase)
    except InvalidPrivateKeyError as err:
        return (
            None,
            DestinationTestStepResult(
                status=Status.FAILED,
                message=f"An error occurred when attempting to load configured private key: {err}",
            ),
        )
    return (private_key_bytes, None)


class SnowflakeEstablishConnectionTestStep(DestinationTestStep):
    """Test whether we can establish a connection to Snowflake.

    Attributes:
        account: Snowflake account ID.
        user: Username used to authenticate in Snowflake.
        role: Role to assume in Snowflake.
        password: If using password authentication, the password for the user.
        private_key: If using key authentication, the private key for the user.
        private_key_passphrase: The passphrase for the private key, if any.
    """

    name = "Establish connection to Snowflake"
    description = "Attempt to establish a Snowflake connection with the provided configuration values."

    def __init__(
        self,
        account: str | None = None,
        user: str | None = None,
        role: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
    ) -> None:
        super().__init__()
        self.account = account
        self.user = user
        self.role = role
        self.password = password
        self.private_key = private_key
        self.private_key_passphrase = private_key_passphrase

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.account is None or self.user is None or (self.private_key is None and self.password is None):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        import snowflake.connector
        from snowflake.connector.errors import DatabaseError, InterfaceError, OperationalError

        private_key, result = try_load_private_key(self.private_key, self.private_key_passphrase)
        if result is not None:
            return result

        try:
            connection = await asyncio.to_thread(
                snowflake.connector.connect,
                user=self.user,
                password=self.password,
                account=self.account,
                private_key=private_key,
                # wrap role in quotes in case it contains lowercase or special characters
                role=f'"{self.role}"' if self.role is not None else None,
            )
        except (OperationalError, InterfaceError, DatabaseError) as err:
            if err.msg is not None and "404 Not Found" in err.msg:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message="Could not establish a connection to Snowflake as the resolved URL does not exist. This usually indicates an invalid Snowflake account.",
                )
            else:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"Could not establish a connection to Snowflake. Received error '{err.errno}': {err.msg}",
                )

        await asyncio.to_thread(connection.close)

        return DestinationTestStepResult(
            status=Status.PASSED,
        )


class SnowflakeWarehouseTestStep(DestinationTestStep):
    """Test whether we can use the configured Snowflake warehouse.

    Attributes:
        account: Snowflake account ID.
        user: Username used to authenticate in Snowflake.
        role: Role to assume in Snowflake.
        password: If using password authentication, the password for the user.
        private_key: If using key authentication, the private key for the user.
        private_key_passphrase: The passphrase for the private key, if any.
        warehouse: The warehouse we are evaluating.
    """

    name = "Verify Snowflake warehouse"
    description = "Verify the configured Snowflake warehouse exists and we have the necessary permissions to use it."

    def __init__(
        self,
        account: str | None = None,
        user: str | None = None,
        role: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse: str | None = None,
    ) -> None:
        super().__init__()
        self.account = account
        self.user = user
        self.role = role
        self.password = password
        self.private_key = private_key
        self.private_key_passphrase = private_key_passphrase
        self.warehouse = warehouse

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.account is None
            or self.user is None
            or (self.private_key is None and self.password is None)
            or self.warehouse is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Internal method with execution logic for test step."""
        import snowflake.connector
        from snowflake.connector.errors import ProgrammingError

        private_key, result = try_load_private_key(self.private_key, self.private_key_passphrase)
        if result is not None:
            return result

        connection = await asyncio.to_thread(
            snowflake.connector.connect,
            user=self.user,
            password=self.password,
            account=self.account,
            private_key=private_key,
            role=f'"{self.role}"' if self.role is not None else None,
        )

        with connection.cursor() as cursor:
            try:
                _ = cursor.execute(f'USE WAREHOUSE "{self.warehouse}"')
            except ProgrammingError as err:
                if err.msg is not None and "Object does not exist" in err.msg:
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"The configured warehouse '{self.warehouse}' does not exist or we are missing 'USAGE' permissions on it.",
                    )
                else:
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"Could not use Snowflake warehouse '{self.warehouse}'. Received error: {err}.",
                    )

        return DestinationTestStepResult(
            status=Status.PASSED,
        )


class SnowflakeDatabaseTestStep(DestinationTestStep):
    """Test whether we can use the configured Snowflake database.

    Attributes:
        account: Snowflake account ID.
        user: Username used to authenticate in Snowflake.
        role: Role to assume in Snowflake.
        password: If using password authentication, the password for the user.
        private_key: If using key authentication, the private key for the user.
        private_key_passphrase: The passphrase for the private key, if any.
        warehouse: The Snowflake warehouse containing the database we are evaluating.
        database: The Snowflake database we are evaluating.
    """

    name = "Verify Snowflake database"
    description = "Verify the configured Snowflake database exists and we have the necessary permissions to use it."

    def __init__(
        self,
        account: str | None = None,
        user: str | None = None,
        role: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse: str | None = None,
        database: str | None = None,
    ) -> None:
        super().__init__()
        self.account = account
        self.user = user
        self.role = role
        self.password = password
        self.private_key = private_key
        self.private_key_passphrase = private_key_passphrase
        self.warehouse = warehouse
        self.database = database

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.account is None
            or self.user is None
            or (self.private_key is None and self.password is None)
            or self.warehouse is None
            or self.database is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Internal method with execution logic for test step."""
        import snowflake.connector
        from snowflake.connector.errors import ProgrammingError

        private_key, result = try_load_private_key(self.private_key, self.private_key_passphrase)
        if result is not None:
            return result

        connection = await asyncio.to_thread(
            snowflake.connector.connect,
            user=self.user,
            password=self.password,
            account=self.account,
            private_key=private_key,
            role=f'"{self.role}"' if self.role is not None else None,
            warehouse=self.warehouse,
        )

        with connection:
            with connection.cursor() as cursor:
                try:
                    _ = cursor.execute(f'USE DATABASE "{self.database}"')
                except ProgrammingError as err:
                    if err.msg is not None and "Object does not exist" in err.msg:
                        return DestinationTestStepResult(
                            status=Status.FAILED,
                            message=f"The configured database '{self.database}' does not exist or we are missing 'USAGE' permissions on it.",
                        )
                    else:
                        return DestinationTestStepResult(
                            status=Status.FAILED,
                            message=f"Could not use Snowflake database '{self.database}'. Received error: {err}.",
                        )

        return DestinationTestStepResult(
            status=Status.PASSED,
        )


class SnowflakeSchemaTestStep(DestinationTestStep):
    """Test whether we can use the configured Snowflake schema.

    Attributes:
        account: Snowflake account ID.
        user: Username used to authenticate in Snowflake.
        role: Role to assume in Snowflake.
        password: If using password authentication, the password for the user.
        private_key: If using key authentication, the private key for the user.
        private_key_passphrase: The passphrase for the private key, if any.
        warehouse: The Snowflake warehouse containing the database.
        database: The Snowflake database containing the schema.
        schema: The Snowflake schema we are evaluating.
    """

    name = "Verify Snowflake schema"
    description = "Verify the configured Snowflake schema exists and we have the necessary permissions to use it."

    def __init__(
        self,
        account: str | None = None,
        user: str | None = None,
        role: str | None = None,
        password: str | None = None,
        private_key: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> None:
        super().__init__()
        self.account = account
        self.user = user
        self.role = role
        self.password = password
        self.private_key = private_key
        self.private_key_passphrase = private_key_passphrase
        self.warehouse = warehouse
        self.database = database
        self.schema = schema

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.account is None
            or self.user is None
            or (self.private_key is None and self.password is None)
            or self.warehouse is None
            or self.database is None
            or self.schema is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Internal method with execution logic for test step."""
        import snowflake.connector
        from snowflake.connector.errors import ProgrammingError

        private_key, result = try_load_private_key(self.private_key, self.private_key_passphrase)
        if result is not None:
            return result

        connection = await asyncio.to_thread(
            snowflake.connector.connect,
            user=self.user,
            password=self.password,
            account=self.account,
            private_key=private_key,
            role=f'"{self.role}"' if self.role is not None else None,
            warehouse=self.warehouse,
        )

        with connection:
            with connection.cursor() as cursor:
                _ = cursor.execute(f'USE DATABASE "{self.database}"')

                try:
                    _ = cursor.execute(f'USE SCHEMA "{self.schema}"')
                except ProgrammingError as err:
                    if err.msg is not None and "Object does not exist" in err.msg:
                        return DestinationTestStepResult(
                            status=Status.FAILED,
                            message=f"The configured schema '{self.schema}' does not exist or we are missing 'USAGE' permissions on it.",
                        )
                    else:
                        return DestinationTestStepResult(
                            status=Status.FAILED,
                            message=f"Could not use Snowflake schema '{self.schema}'. Received error: {err}.",
                        )

        return DestinationTestStepResult(
            status=Status.PASSED,
        )


class SnowflakeDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for Snowflake."""

    def __init__(self):
        self.account = None
        self.user = None
        self.role = None
        self.password = None
        self.private_key = None
        self.private_key_passphrase = None
        self.warehouse = None
        self.database = None
        self.schema = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.account = kwargs.get("account", None)
        self.user = kwargs.get("user", None)
        self.role = kwargs.get("role", None)
        self.password = kwargs.get("password", None)
        self.private_key = kwargs.get("private_key", None)
        self.private_key_passphrase = kwargs.get("private_key_passphrase", None)
        self.warehouse = kwargs.get("warehouse", None)
        self.database = kwargs.get("database", None)
        self.schema = kwargs.get("schema", None)

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            SnowflakeEstablishConnectionTestStep(
                account=self.account,
                user=self.user,
                role=self.role,
                password=self.password,
                private_key=self.private_key,
                private_key_passphrase=self.private_key_passphrase,
            ),
            SnowflakeWarehouseTestStep(
                account=self.account,
                user=self.user,
                role=self.role,
                password=self.password,
                private_key=self.private_key,
                private_key_passphrase=self.private_key_passphrase,
                warehouse=self.warehouse,
            ),
            SnowflakeDatabaseTestStep(
                account=self.account,
                user=self.user,
                role=self.role,
                password=self.password,
                private_key=self.private_key,
                private_key_passphrase=self.private_key_passphrase,
                warehouse=self.warehouse,
                database=self.database,
            ),
            SnowflakeSchemaTestStep(
                account=self.account,
                user=self.user,
                role=self.role,
                password=self.password,
                private_key=self.private_key,
                private_key_passphrase=self.private_key_passphrase,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
            ),
        ]
