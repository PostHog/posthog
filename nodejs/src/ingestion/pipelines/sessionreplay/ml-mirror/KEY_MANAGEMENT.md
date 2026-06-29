# ML-mirror pseudonym key — generate & store before deploying

The mirror pseudonymizes ids (`session_id`, `team_id`, `distinct_id`) with a
keyed HMAC. The key must be **stable forever**: rotating it re-maps every id
and contaminates train/eval splits, so the loader (`pseudonym-key.ts`) fails
closed on a fingerprint mismatch. Generate it once, store it KMS-wrapped, pin
its fingerprint, and never rotate it.

Only the **mirror ingester** deployment needs the key (it builds the rows).
The **Parquet-sink** deployment reads already-pseudonymized rows from Kafka
and needs no key.

## One-time setup

1. **Generate a high-entropy key** (32 random bytes — the raw HMAC secret).
   Do this in a trusted, ephemeral shell; the plaintext must never land in
   source control, env files, or logs.

   ```bash
   head -c 32 /dev/urandom > pseudonym.key
   ```

2. **Wrap it with KMS.** In the ML account, use (or create) a symmetric
   encrypt/decrypt CMK and grant the mirror's runtime role `kms:Decrypt` on
   it. Encrypt the raw key and base64-encode the ciphertext blob:

   ```bash
   aws kms encrypt --key-id <cmk-arn> --plaintext fileb://pseudonym.key \
     --query CiphertextBlob --output text   # base64 — the CIPHERTEXT value
   ```

3. **Compute the fingerprint** of the *plaintext* key (non-reversible, safe to
   store/log) so you can pin it. It is
   `HMAC-SHA256(key, "pseudonym-key-fingerprint:v1")` truncated to 16 hex
   chars — call `pseudonymKeyFingerprint(fs.readFileSync("pseudonym.key"))`
   from a `tsx`/jest scratch.

4. **Configure the mirror ingester** with the wrapped key + region + pinned
   fingerprint:

   - `SESSION_RECORDING_ML_PSEUDONYM_KEY_CIPHERTEXT` = base64 ciphertext (2)
   - `SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION` = the CMK's region (empty →
     SDK default chain)
   - `SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT` = fingerprint (3)
   - Leave `SESSION_RECORDING_ML_PSEUDONYM_SECRET` **unset** in prod (it's the
     local-dev plaintext fallback).

5. **Destroy the plaintext**, keeping only a sealed offline backup for
   break-glass recovery:

   ```bash
   shred -u pseudonym.key
   ```

## Verify on startup

The mirror logs once at boot:

```text
🔑 ml_pseudonym_key_loaded { source: "kms", fingerprint: "<hex>", pinned: true }
```

`source: "kms"` and `pinned: true` confirm the wrapped key was used and the
fingerprint guard is active. If the key ever resolves to a different
fingerprint, the process refuses to start rather than silently re-map ids.
