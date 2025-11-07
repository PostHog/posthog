import asyncio
from datetime import timedelta
import uuid

import structlog
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from posthog.models import User
from posthog.models.exported_asset import ExportedAsset
from django.utils.timezone import now

from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

logger = structlog.get_logger(__name__)
base_user = User.objects.get(email="alex.l@posthog.com")

SESSIONS_DATA = {
    "0199fb43-205d-70e6-b49c-a88a75939b26": { "processed": False, "duration": 584 },
    "0199fb3e-fa8b-787f-94b0-19ad7487e946": { "processed": False, "duration": 489 },
    "0199fb3d-e307-7f3c-81d8-88144f17ca53": { "processed": False, "duration": 454 },
    "0199fb3c-e680-7092-aaea-85744be495dc": { "processed": False, "duration": 203 },
    "0199fb3c-b533-731a-98ce-17472e8b0942": { "processed": False, "duration": 208 },
    "0199fb3b-7cb4-7872-a84e-8de447fb3c5f": { "processed": False, "duration": 533 },
    "0199fb3a-6302-7b73-bc29-d110725d4221": { "processed": False, "duration": 152 },
    "0199fb3a-064f-772f-b162-bc3fb4968415": { "processed": False, "duration": 366 },
    "0199fb37-e8aa-7f83-a348-b0c42781f296": { "processed": False, "duration": 569 },
    "0199fb36-f087-737a-899f-a1333e8b57cd": { "processed": False, "duration": 339 },
    "0199fb35-964e-7e84-921c-2b345f018a22": { "processed": False, "duration": 530 },
    "0199fb35-8308-7df8-b634-6682e92370f9": { "processed": False, "duration": 500 },
    "0199fb35-3d28-7e72-9716-9b5070ec3c1d": { "processed": False, "duration": 238 },
    "0199fb34-b2d3-7eba-a2e7-c46bda205bc9": { "processed": False, "duration": 352 },
    "0199fb34-9855-75e2-b9c4-9b7266acaa7a": { "processed": False, "duration": 210 },
    "0199fb30-09a1-75c3-9039-503d8b0dc306": { "processed": False, "duration": 283 },
    "0199fb2b-06dc-78ff-a5d1-76b65fa0b752": { "processed": False, "duration": 583 },
    "0199fb2c-bd07-7b84-a747-d2495d391454": { "processed": False, "duration": 517 },
    "0199fb2c-8da1-7611-8eba-a0113f3e9036": { "processed": False, "duration": 590 },
    "0199fb27-ba4f-739a-a584-b92ba949529d": { "processed": False, "duration": 137 },
    "0199fb18-c248-7ea3-820c-2056876d731b": { "processed": False, "duration": 427 },
    "0199fb22-705f-7b96-957a-fe93b7f50623": { "processed": False, "duration": 178 },
    "0199fb17-db08-7194-a898-e092bc52e43b": { "processed": False, "duration": 583 },
    "0199fb19-cb57-7bba-8868-441edf8c119c": { "processed": False, "duration": 449 },
    "0199fb19-824f-7346-8a07-3ca0e8b039b6": { "processed": False, "duration": 196 },
    "0199fb18-4685-79e3-bbd1-d907f947a5af": { "processed": False, "duration": 590 },
    "0199fb14-4d04-78e1-a543-81099fb8d236": { "processed": False, "duration": 252 },
    "0199fb13-f849-79ba-bde5-4efb91f2f409": { "processed": False, "duration": 531 },
    "0199fb13-70d4-7163-94c1-45891b55927a": { "processed": False, "duration": 198 },
    "0199fb13-173d-7f64-81a9-b10c0a25d2ce": { "processed": False, "duration": 209 },
    "0199fb0c-85bc-700e-bb5c-e7bfeb3c20c7": { "processed": False, "duration": 355 },
    "0199fb08-b0cd-7758-b059-f7865b67f375": { "processed": False, "duration": 595 },
    "0199fb04-a74a-7d21-9761-a8a6810def0b": { "processed": False, "duration": 239 },
    "0199fafe-f2e7-7b6b-b22b-087ec9b3b9d2": { "processed": False, "duration": 594 },
    "0199fafe-321a-7a5a-819a-06e6c3fe60e1": { "processed": False, "duration": 487 },
    "0199fafb-f5e6-7cd4-bb0c-af5a4c97c79d": { "processed": False, "duration": 508 },
    "0199faf7-2c22-709e-9e9b-ff04f3d3dcf5": { "processed": False, "duration": 321 },
    "0199faa4-5cd0-7a64-bf8d-0dcbe6776077": { "processed": False, "duration": 211 },
    "0199fad3-68d4-7a39-a8d3-5e2711a5f78a": { "processed": False, "duration": 154 },
    "0199faf3-d2b0-7252-be9e-bf8862499328": { "processed": False, "duration": 583 },
    "0199faf1-8fa8-7244-b76a-4cfda0b57676": { "processed": False, "duration": 377 },
    "0199faef-6d82-7539-aa11-43e88c96c3d7": { "processed": False, "duration": 217 },
    "0199face-2440-7ed5-aa02-1e7d16646a5e": { "processed": False, "duration": 295 },
    "0199fae2-89ec-7a45-b1c8-dfd693d8e0af": { "processed": False, "duration": 560 },
    "0199fae2-5909-75bb-a7e0-e93f80bba9a8": { "processed": False, "duration": 594 },
    "0199fadf-f550-764d-a40a-6634b2c4b229": { "processed": False, "duration": 456 },
    "0199fad6-8914-7ee1-b107-f20af75f7f12": { "processed": False, "duration": 589 },
    "0199fad4-f66c-752d-852c-272a8666fc2c": { "processed": False, "duration": 542 },
    "0199fa70-4140-721f-9238-6536e220235c": { "processed": False, "duration": 446 },
    "0199fac3-7009-7504-8c5d-7698a25ab2f0": { "processed": False, "duration": 419 },
    "0199fabf-2933-74b9-88cf-4be63342f86a": { "processed": False, "duration": 543 },
    "0199fabb-3069-7cc4-97c3-ecf2067c70a9": { "processed": False, "duration": 440 },
    "0199fab9-2933-7e26-94f3-16f5f6b982b9": { "processed": False, "duration": 439 },
    "0199fab7-b508-73f9-ab78-0d284cfee4fb": { "processed": False, "duration": 521 },
    "0199fab6-95e6-7191-a3ee-4682c09ed762": { "processed": False, "duration": 348 },
    "0199fab1-98d8-72cb-804b-4b29f4357f11": { "processed": False, "duration": 529 },
    "0199faa9-a1aa-78ac-8f50-3ff339255a36": { "processed": False, "duration": 203 },
    "0199faa8-c822-77a2-8d49-a9fa9bf4d3cd": { "processed": False, "duration": 178 },
    "0199faa8-dc73-77ca-9e95-1fd808e3dc11": { "processed": False, "duration": 182 },
    "0199faa3-cfc4-7f9e-8499-9114acf24466": { "processed": False, "duration": 184 },
    "0199fa85-5dab-7313-af25-5b631ea997cb": { "processed": False, "duration": 597 },
    "0199faa1-838b-7112-b552-ff0308cd679e": { "processed": False, "duration": 381 },
    "0199fa9f-d966-7c03-800b-ebc0465fa278": { "processed": False, "duration": 429 },
    "0199fa9e-6638-7527-83d1-f14bfd631337": { "processed": False, "duration": 374 },
    "0199fa8b-141a-73cd-afae-b0a4121bf282": { "processed": False, "duration": 166 },
    "0199fa95-29aa-7878-80d8-3009c48bd514": { "processed": False, "duration": 496 },
    "0199fa89-8758-719d-9626-d3896a0598de": { "processed": False, "duration": 503 },
    "0199fa88-c8dd-710c-b78f-9dfc83fe443f": { "processed": False, "duration": 405 },
    "0199fa86-f370-78f0-a721-11df68a44781": { "processed": False, "duration": 267 },
    "0199fa85-7476-7234-81ec-9c576463310f": { "processed": False, "duration": 239 },
    "0199fa05-741e-7557-8ba7-5dd4e6ed5b2f": { "processed": False, "duration": 204 },
    "0199fa72-e819-7143-95b4-1d0da2b3bcde": { "processed": False, "duration": 209 },
    "0199fa71-0bd3-76df-ae66-2aee23b118ef": { "processed": False, "duration": 528 },
    "0199fa6f-5efe-7ec9-a7fe-785d0668f929": { "processed": False, "duration": 418 },
    "0199fa6f-2ded-77ce-92e6-9e06d8a68502": { "processed": False, "duration": 583 },
    "0199fa6d-f790-7816-a56d-399a3b907314": { "processed": False, "duration": 161 },
    "0199fa6e-1f7b-7cf2-971b-66cd6e7b88b9": { "processed": False, "duration": 538 },
    "0199fa6a-3c57-708a-9472-da12cbdb7bc5": { "processed": False, "duration": 339 },
    "0199fa36-985b-71d8-9d77-22f641b1b459": { "processed": False, "duration": 203 },
    "0199fa62-1c7b-7c26-be36-41ff708d7379": { "processed": False, "duration": 516 },
    "0199fa55-709c-7dab-8304-0e6be342a1bd": { "processed": False, "duration": 332 },
    "0199fa5e-5a42-70ab-81cd-a1c97401b436": { "processed": False, "duration": 358 },
    "0199fa5b-56fb-7446-8dc5-07c28e32d456": { "processed": False, "duration": 560 },
    "0199fa57-8d9d-76b7-a8a8-76f13dc3ed1e": { "processed": False, "duration": 213 },
    "0199fa56-571a-793a-b6d5-391771ea4041": { "processed": False, "duration": 147 },
    "0199fa34-fa54-74c0-bd34-aae9c233312e": { "processed": False, "duration": 524 },
    "0199fa50-95cd-7cd4-a32e-d639a90e89d0": { "processed": False, "duration": 331 },
    "0199fa4f-4012-71b1-9d4f-320055c4005a": { "processed": False, "duration": 165 },
    "0199fa4d-d6bc-7252-ad14-d02b64cca228": { "processed": False, "duration": 300 },
    "0199fa39-3689-77dd-8c2e-0f67ce89f548": { "processed": False, "duration": 553 },
    "0199fa4a-49b0-701c-87f9-dc3847377f2f": { "processed": False, "duration": 196 },
    "0199fa49-e2c8-761a-aae0-89df8b90767a": { "processed": False, "duration": 519 },
    "0199fa35-f4d0-7fa3-b8d6-d9fed036904c": { "processed": False, "duration": 585 },
    "0199fa43-dcc1-7903-bde8-4f6f7e652e5c": { "processed": False, "duration": 423 },
    "0199fa40-7c8f-7c66-b63a-b16de4f2aa93": { "processed": False, "duration": 247 },
    "0199fa3c-7e56-7fb1-9c4c-96f2f24aa3a0": { "processed": False, "duration": 547 },
    "0199fa3b-fcf9-79f5-b48b-b6fb097a5ac7": { "processed": False, "duration": 394 },
    "0199fa31-b50d-73f1-9423-2f90db3810b8": { "processed": False, "duration": 491 },
    "0199fa2e-93cd-7d67-a685-c580fa3100e6": { "processed": False, "duration": 274 },
    "0199fa2b-dd7a-7894-8fa7-20ab5a6ee2c9": { "processed": False, "duration": 318 }
}

PLAYBACK_SPEED = 4
VIDEO_FORMAT = "webm"
LABEL = "100_18-10-25"


async def _export_video_start_task(session_id: str, user: User, duration_s: int):
    created_at = now()
    expires_after = created_at + timedelta(days=3)
    exported_asset = await ExportedAsset.objects.acreate(
        team_id=2,
        export_format=f"video/{VIDEO_FORMAT}",
        export_context={
            "session_recording_id": session_id,
            "filename": f"fd-{LABEL}-video-export_{session_id}_x{PLAYBACK_SPEED}.{VIDEO_FORMAT}",
            "timestamp": 0,
            "duration": duration_s,
            # Speed up to reduce the rendering time
            "playback_speed": PLAYBACK_SPEED,
            # Keeping default values
            "mode": "screenshot",
        },
        created_by=user,
        created_at=created_at,
        expires_after=expires_after,
    )
    # Generate a video through Temporal workflow
    client = await async_connect()
    await client.execute_workflow(
        VideoExportWorkflow.run,
        VideoExportInputs(exported_asset_id=exported_asset.id),
        id=f"fd-{LABEL}-video-export_x{PLAYBACK_SPEED}_{VIDEO_FORMAT}_{session_id}_{uuid.uuid4()}",
        task_queue="video-export-task-queue",
        retry_policy=RetryPolicy(maximum_attempts=int(3)),
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )


CHUNK_SIZE = 5


async def export_videos(user: User):
    chunk_size = CHUNK_SIZE
    # Split sessions into chunks
    for i in range(0, len(SESSIONS_DATA), chunk_size):
        chunk = list(SESSIONS_DATA.items())[i : i + chunk_size]
        logger.info(
            f"Exporting session ids (chunk {i // chunk_size + 1} of {len(SESSIONS_DATA) // chunk_size}): "
            f"{', '.join([session_id for session_id, _ in chunk])}"
        )
        await asyncio.gather(
            *[
                _export_video_start_task(session_id, base_user, session_data["duration"])
                for session_id, session_data in chunk
                if not session_data["processed"]
            ]
        )


asyncio.run(export_videos(base_user))
