"""
Utility script to handle stuck backups in CREATING_BACKUP status
"""

from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster


def check_and_cleanup_stuck_backups(
    cluster: ClickhouseCluster, workload: Workload = Workload.ONLINE, stuck_threshold_hours: int = 4
):
    """
    Check for backups stuck in CREATING_BACKUP status and clean them up.

    A backup is considered stuck if:
    1. Status is CREATING_BACKUP
    2. No corresponding process is running
    3. Last event_time is older than threshold
    """

    def check_host_for_stuck_backups(client: Client):
        # Find backups in CREATING_BACKUP status
        stuck_backups = client.execute(
            """
            SELECT
                name,
                hostname(),
                status,
                event_time_microseconds,
                error
            FROM system.backup_log
            WHERE
                status = 'CREATING_BACKUP'
                AND event_time_microseconds < now() - interval {hours} hour
            ORDER BY event_time_microseconds DESC
        """.format(hours=stuck_threshold_hours)
        )

        results = []
        for backup_name, hostname, status, event_time, error in stuck_backups:
            # Check if there's an active process for this backup
            active_process = client.execute(f"""
                SELECT count()
                FROM system.processes
                WHERE query_kind = 'Backup' AND query LIKE '%{backup_name}%'
            """)[0][0]

            if active_process == 0:
                # No active process, this backup is stuck
                results.append(
                    {
                        "name": backup_name,
                        "hostname": hostname,
                        "status": status,
                        "event_time": event_time,
                        "error": error or "No error recorded - likely interrupted",
                        "action": "NEEDS_CLEANUP",
                    }
                )

        return results

    # Check all data nodes for stuck backups
    stuck_backups = cluster.map_hosts_by_role(
        fn=check_host_for_stuck_backups, node_role=NodeRole.DATA, workload=workload
    ).result()

    all_stuck = []
    for _host, backups in stuck_backups.items():
        if backups:
            all_stuck.extend(backups)

    return all_stuck


def force_mark_backup_failed(
    cluster: ClickhouseCluster, backup_name: str, hostname: str, workload: Workload = Workload.ONLINE
):
    """
    Force mark a stuck backup as failed in the backup_log.
    This allows new backups to proceed.
    """

    def update_backup_status(client: Client):
        # Insert a new entry marking the backup as failed
        client.execute(f"""
            INSERT INTO system.backup_log (
                hostname,
                event_date,
                event_time,
                event_time_microseconds,
                id,
                name,
                status,
                error,
                start_time,
                end_time
            )
            SELECT
                hostname(),
                today(),
                now(),
                now64(),
                id,
                name,
                'BACKUP_FAILED',
                'Backup was stuck in CREATING_BACKUP status and forcefully marked as failed',
                start_time,
                now()
            FROM system.backup_log
            WHERE name = '{backup_name}'
            ORDER BY event_time_microseconds DESC
            LIMIT 1
        """)

        return f"Marked backup {backup_name} as FAILED on {hostname}"

    # Execute on the specific host
    result = cluster.execute_on_host(hostname=hostname, fn=update_backup_status, workload=workload)

    return result


# Example usage:
#
# 1. Import and check for stuck backups:
#    from dags.backups_stuck_fix import check_and_cleanup_stuck_backups
#    stuck = check_and_cleanup_stuck_backups(cluster)
#
# 2. Force mark a stuck backup as failed:
#    from dags.backups_stuck_fix import force_mark_backup_failed
#    result = force_mark_backup_failed(
#        cluster,
#        'posthog/sharded_events/2/2025-09-07T08:00:01Z',
#        'prod-iad-ch-2f.internal.ec2.us-east-1.prod.posthog.dev'
#    )
