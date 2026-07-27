# Test cases for openai-hipaa-eligible-endpoints rules.
# ruff: noqa: F841, F401, E501 — assignments exist solely so semgrep has something to match.

from openai import AsyncOpenAI, OpenAI

client = OpenAI()
async_client = AsyncOpenAI()


# ============================================================
# openai-non-hipaa-assistants-threads — should FLAG
# ============================================================


def test_assistants_beta_attr() -> None:
    # ruleid: openai-non-hipaa-assistants-threads
    a = client.beta.assistants


def test_threads_beta_attr() -> None:
    # ruleid: openai-non-hipaa-assistants-threads
    t = client.beta.threads


def test_assistants_create() -> None:
    # ruleid: openai-non-hipaa-assistants-threads
    client.assistants.create(name="x", model="gpt-4")


def test_threads_create() -> None:
    # ruleid: openai-non-hipaa-assistants-threads
    client.threads.create()


# ============================================================
# openai-non-hipaa-assistants-threads — should NOT flag
# ============================================================


def test_chat_completions_ok() -> None:
    # ok: openai-non-hipaa-assistants-threads
    client.chat.completions.create(model="gpt-4", messages=[])


def test_responses_ok() -> None:
    # ok: openai-non-hipaa-assistants-threads
    client.responses.create(model="gpt-4.1-mini", input="hi")


# ============================================================
# openai-non-hipaa-fine-tuning — should FLAG
# ============================================================


def test_fine_tuning_jobs_create() -> None:
    # ruleid: openai-non-hipaa-fine-tuning
    client.fine_tuning.jobs.create(training_file="file-x", model="gpt-4")


def test_fine_tuning_direct_method() -> None:
    # ruleid: openai-non-hipaa-fine-tuning
    client.fine_tuning.list()


def test_fine_tuning_jobs_retrieve() -> None:
    # ruleid: openai-non-hipaa-fine-tuning
    client.fine_tuning.jobs.retrieve("ftjob-x")


# ============================================================
# openai-non-hipaa-realtime — should FLAG
# ============================================================


def test_realtime_method() -> None:
    # ruleid: openai-non-hipaa-realtime
    client.realtime.connect()


def test_beta_realtime_method() -> None:
    # ruleid: openai-non-hipaa-realtime
    client.beta.realtime.connect()


def test_beta_realtime_nested() -> None:
    # ruleid: openai-non-hipaa-realtime
    client.beta.realtime.sessions.create(model="gpt-4o-realtime")


# ============================================================
# openai-non-hipaa-legacy-completions — should FLAG
# ============================================================


def test_legacy_completions_create() -> None:
    # ruleid: openai-non-hipaa-legacy-completions
    client.completions.create(model="text-davinci-003", prompt="hi")


def test_legacy_completions_create_async() -> None:
    # ruleid: openai-non-hipaa-legacy-completions
    async_client.completions.create(model="text-davinci-003", prompt="hi")


# ============================================================
# openai-non-hipaa-legacy-completions — should NOT flag
# ============================================================


def test_chat_completions_create() -> None:
    # ok: openai-non-hipaa-legacy-completions
    client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": "hi"}])


def test_chat_completions_create_async() -> None:
    # ok: openai-non-hipaa-legacy-completions
    async_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": "hi"}])


# ============================================================
# Other eligible endpoints — should NOT flag any rule
# ============================================================


def test_embeddings_ok() -> None:
    # ok: openai-non-hipaa-assistants-threads
    # ok: openai-non-hipaa-fine-tuning
    # ok: openai-non-hipaa-realtime
    # ok: openai-non-hipaa-legacy-completions
    client.embeddings.create(model="text-embedding-3-small", input="hello")


def test_moderations_ok() -> None:
    # ok: openai-non-hipaa-assistants-threads
    # ok: openai-non-hipaa-fine-tuning
    # ok: openai-non-hipaa-realtime
    # ok: openai-non-hipaa-legacy-completions
    client.moderations.create(input="hello")


def test_audio_transcriptions_ok() -> None:
    # ok: openai-non-hipaa-assistants-threads
    # ok: openai-non-hipaa-fine-tuning
    # ok: openai-non-hipaa-realtime
    # ok: openai-non-hipaa-legacy-completions
    client.audio.transcriptions.create(model="whisper-1", file=b"")
