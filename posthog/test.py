from posthog.warehouse.models.external_data_source import ExternalDataSource
from urllib.parse import quote
from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool
from dlt.sources.credentials import ConnectionStringCredentials
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.temporal.data_imports.pipelines.sql_database import engine_from_credentials
from sqlalchemy import Table
from sqlalchemy import MetaData

model = ExternalDataSource.objects.get(id="01928e04-e40b-0000-b204-b1b0a9a55786")
host = quote(model.job_inputs.get("host"))
user = quote(model.job_inputs.get("user"))
password = quote(model.job_inputs.get("password"))
database = quote(model.job_inputs.get("database"))
sslmode = quote("prefer")
port = quote(model.job_inputs.get("port"))

using_ssh_tunnel = str(model.job_inputs.get("ssh_tunnel_enabled", False)) == "True"
ssh_tunnel_host = model.job_inputs.get("ssh_tunnel_host")
ssh_tunnel_port = model.job_inputs.get("ssh_tunnel_port")
ssh_tunnel_auth_type = model.job_inputs.get("ssh_tunnel_auth_type")
ssh_tunnel_auth_type_username = model.job_inputs.get("ssh_tunnel_auth_type_username")
ssh_tunnel_auth_type_password = model.job_inputs.get("ssh_tunnel_auth_type_password")
ssh_tunnel_auth_type_passphrase = model.job_inputs.get("ssh_tunnel_auth_type_passphrase")
ssh_tunnel_auth_type_private_key = model.job_inputs.get("ssh_tunnel_auth_type_private_key")


ssh_tunnel = SSHTunnel(
    enabled=using_ssh_tunnel,
    host=ssh_tunnel_host,
    port=ssh_tunnel_port,
    auth_type=ssh_tunnel_auth_type,
    username=ssh_tunnel_auth_type_username,
    password=ssh_tunnel_auth_type_password,
    passphrase=ssh_tunnel_auth_type_passphrase,
    private_key=ssh_tunnel_auth_type_private_key,
)

with ssh_tunnel.get_tunnel(host, int(port)) as tunnel:
    tunnel_port = tunnel.local_bind_port
    tunnel_host = tunnel.local_bind_host
    is_debug = get_from_env("DEBUG", False, type_cast=str_to_bool)
    ssl_ca = "/etc/ssl/cert.pem" if is_debug else "/etc/ssl/certs/ca-certificates.crt"
    credentials = ConnectionStringCredentials(
        f"mysql+pymysql://{user}:{password}@{tunnel_host}:{tunnel_port}/{database}?ssl_ca={ssl_ca}&ssl_verify_cert=false"
    )
    engine = engine_from_credentials(credentials)
    engine.execution_options(stream_results=True)
    metadata = MetaData(schema=None)
    metadata.reflect(bind=engine)

    Table("t_billing_company", MetaData(schema=None), autoload_with=engine)
