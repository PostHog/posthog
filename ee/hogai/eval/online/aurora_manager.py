import re

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


class AuroraEvalDatabaseManager:
    """Creates and destroys per-eval-run databases on a shared Aurora instance."""

    def __init__(
        self,
        host: str,
        port: str,
        admin_user: str,
        admin_password: str,
        admin_database: str = "postgres",
    ):
        self.host = host
        self.port = port
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.admin_database = admin_database

    def _admin_connection(self):
        conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.admin_user,
            password=self.admin_password,
            dbname=self.admin_database,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        return conn

    @staticmethod
    def _sanitize_run_id(run_id: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", run_id)[:50]
        return f"eval_run_{sanitized}"

    def create_eval_database(self, run_id: str) -> str:
        db_name = self._sanitize_run_id(run_id)
        conn = self._admin_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        finally:
            conn.close()
        return db_name

    def cleanup_eval_database(self, run_id: str) -> None:
        db_name = self._sanitize_run_id(run_id)
        conn = self._admin_connection()
        try:
            with conn.cursor() as cur:
                # Terminate active connections before dropping
                cur.execute(
                    sql.SQL(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()"
                    ),
                    [db_name],
                )
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
        finally:
            conn.close()
