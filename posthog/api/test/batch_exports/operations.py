from django.test.client import Client as TestClient

from rest_framework import status


def create_batch_export(client: TestClient, team_id: int, batch_export_data: dict):
    return client.post(f"/api/projects/{team_id}/batch_exports", batch_export_data, content_type="application/json")


def create_batch_export_ok(client: TestClient, team_id: int, batch_export_data: dict):
    response = create_batch_export(client, team_id, batch_export_data)
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    return response.json()


def pause_batch_export(client: TestClient, team_id: int, batch_export_id: int):
    return client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/pause")


def pause_batch_export_ok(client: TestClient, team_id: int, batch_export_id: int):
    response = pause_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def unpause_batch_export(client: TestClient, team_id: int, batch_export_id: int):
    return client.post(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/unpause")


def unpause_batch_export_ok(client: TestClient, team_id: int, batch_export_id: int):
    response = unpause_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def get_batch_export(client: TestClient, team_id: int, batch_export_id: int):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}")


def get_batch_export_ok(client: TestClient, team_id: int, batch_export_id: int):
    response = get_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def get_batch_export_runs(client: TestClient, team_id: int, batch_export_id: str):
    return client.get(f"/api/projects/{team_id}/batch_exports/{batch_export_id}/runs", content_type="application/json")


def get_batch_export_runs_ok(client: TestClient, team_id: int, batch_export_id: str):
    response = get_batch_export_runs(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def delete_batch_export(client: TestClient, team_id: int, batch_export_id: int):
    return client.delete(f"/api/projects/{team_id}/batch_exports/{batch_export_id}")


def delete_batch_export_ok(client: TestClient, team_id: int, batch_export_id: int):
    response = delete_batch_export(client, team_id, batch_export_id)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response
    return response


def list_batch_exports(client: TestClient, team_id: int):
    return client.get(f"/api/projects/{team_id}/batch_exports")


def list_batch_exports_ok(client: TestClient, team_id: int):
    response = list_batch_exports(client, team_id)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()


def backfill_batch_export(client: TestClient, team_id: int, batch_export_id: int, start_at: str, end_at: str):
    return client.post(
        f"/api/projects/{team_id}/batch_exports/{batch_export_id}/backfill",
        {"start_at": start_at, "end_at": end_at},
        content_type="application/json",
    )


def backfill_batch_export_ok(client: TestClient, team_id: int, batch_export_id: int, start_at: str, end_at: str):
    response = backfill_batch_export(client, team_id, batch_export_id, start_at, end_at)
    assert response.status_code == status.HTTP_200_OK, response.json()
    return response.json()
