### Installing MS SQL drivers

To connect any SQL data source, we need to have MS SQL drivers installed locally (due to import references), following [this guide](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos?view=sql-server-ver15#microsoft-odbc-18) from Microsoft, we can get everything up and running on macOS with the below brew install script

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18 mssql-tools18
```

Without this, you'll get the following error when connecting a SQL database to data warehouse:

```text
symbol not found in flat namespace '_bcp_batch'
```

If the issue persists, install from source without cache again

```bash
pip install --pre --no-binary :all: pymssql --no-cache
```

See https://github.com/pymssql/pymssql/issues/769 for a full set of debugging opportunities.

For Apple Silicon machines running into the error consistently, the following command may resolve it.

```bash
uv add git+https://github.com/pymssql/pymssql@master
```
