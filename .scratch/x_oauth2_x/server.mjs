/**
 * Minimal local OAuth 2.0 helper for X (Twitter) user access tokens.
 *
 * 1. Copy `.env.example` → `.env` in this directory and fill values (see keys below).
 * 2. X Developer Portal → User authentication settings:
 *    - OAuth 2.0 enabled, Web App / confidential client
 *    - Callback URL must match REDIRECT_URI (default http://127.0.0.1:8787/callback)
 * 3. Run:  bun server.mjs   or   node server.mjs
 * 4. Open http://127.0.0.1:8787
 *
 * Env vars: X_CLIENT_ID, X_CLIENT_SECRET (required). X_ACCESS_TOKEN, X_REFRESH_TOKEN,
 * X_DM_* optional. Use GET /refresh-token to mint a new access_token from X_REFRESH_TOKEN
 * (needs offline.access scope on initial authorize).
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as http from "node:http";
import * as path from "node:path";
import * as url from "node:url";

/** Load `.env` from this file's directory (no extra deps). Later definitions win over earlier. */
function loadEnvFile() {
	const envPath = path.join(
		path.dirname(url.fileURLToPath(import.meta.url)),
		".env",
	);
	if (!fs.existsSync(envPath)) {
		return;
	}
	const text = fs.readFileSync(envPath, "utf8");
	for (const line of text.split(/\r?\n/)) {
		const trimmed = line.trim();
		if (!trimmed || trimmed.startsWith("#")) {
			continue;
		}
		const eq = trimmed.indexOf("=");
		if (eq === -1) {
			continue;
		}
		const key = trimmed.slice(0, eq).trim().replace(/^export\s+/i, "");
		let val = trimmed.slice(eq + 1).trim();
		if (
			(val.startsWith('"') && val.endsWith('"')) ||
			(val.startsWith("'") && val.endsWith("'"))
		) {
			val = val.slice(1, -1);
		}
		process.env[key] = val;
	}
}

loadEnvFile();

const CLIENT_ID = process.env.X_CLIENT_ID ?? "";
const CLIENT_SECRET = process.env.X_CLIENT_SECRET ?? "";
const ACCESS_TOKEN = process.env.X_ACCESS_TOKEN ?? "";
/** From initial token response; used by GET /refresh-token */
const REFRESH_TOKEN = process.env.X_REFRESH_TOKEN ?? "";
const DM_RECIPIENT_USER_ID = process.env.X_DM_RECIPIENT_USER_ID ?? "";
const DM_MESSAGE_TEXT = process.env.X_DM_MESSAGE_TEXT ?? "";

const PORT = Number(process.env.PORT) || 8787;
const REDIRECT_URI = process.env.REDIRECT_URI || `http://127.0.0.1:${PORT}/callback`;
/** Space-separated OAuth 2.0 scopes (see X docs). */
const SCOPES =
	process.env.SCOPES ||
	"tweet.read users.read dm.read dm.write offline.access";

const AUTH_URL = "https://twitter.com/i/oauth2/authorize";
const TOKEN_URL = "https://api.twitter.com/2/oauth2/token";
/** Override with `https://api.x.com` if you want to mirror docs host exactly. */
const DM_HOST = process.env.DM_HOST || "https://api.twitter.com";

async function verifyAccessTokenUser() {
	const res = await fetch(
		`${DM_HOST}/2/users/me?user.fields=id,name,username`,
		{
			headers: { Authorization: `Bearer ${ACCESS_TOKEN}` },
		},
	);
	const raw = await res.text();
	/** @type {unknown} */
	let body;
	try {
		body = JSON.parse(raw);
	} catch {
		body = { raw };
	}
	return { ok: res.ok, status: res.status, statusText: res.statusText, body };
}

/**
 * 1:1 DM: creates thread if needed. Group creation is POST /2/dm_conversations (different shape).
 * @see https://docs.x.com/x-api/direct-messages/create-dm-message-by-participant-id
 */
async function sendOneToOneDm() {
	const endpoint = `${DM_HOST}/2/dm_conversations/with/${DM_RECIPIENT_USER_ID}/messages`;
	const res = await fetch(endpoint, {
		method: "POST",
		headers: {
			Authorization: `Bearer ${ACCESS_TOKEN}`,
			"Content-Type": "application/json",
		},
		body: JSON.stringify({ text: DM_MESSAGE_TEXT }),
	});
	const raw = await res.text();
	/** @type {unknown} */
	let body;
	try {
		body = JSON.parse(raw);
	} catch {
		body = { raw };
	}
	return { ok: res.ok, status: res.status, statusText: res.statusText, body };
}

/** @type {{ verifier: string; challenge: string; state: string } | null} */
let session = null;

function base64url(buf) {
	return buf.toString("base64url");
}

function newPkcePair() {
	const verifier = base64url(crypto.randomBytes(32));
	const challenge = base64url(
		crypto.createHash("sha256").update(verifier).digest(),
	);
	return { verifier, challenge };
}

function basicAuthHeader() {
	const token = Buffer.from(`${CLIENT_ID}:${CLIENT_SECRET}`, "utf8").toString(
		"base64",
	);
	return `Basic ${token}`;
}

/**
 * Exchange refresh_token for a new access_token (and possibly rotated refresh_token).
 * @see https://docs.x.com/x-api/authentication/oauth-2-0/user-access-token
 */
async function refreshAccessToken() {
	const body = new URLSearchParams({
		grant_type: "refresh_token",
		refresh_token: REFRESH_TOKEN,
	});
	const res = await fetch(TOKEN_URL, {
		method: "POST",
		headers: {
			"Content-Type": "application/x-www-form-urlencoded",
			Authorization: basicAuthHeader(),
		},
		body: body.toString(),
	});
	const raw = await res.text();
	/** @type {unknown} */
	let parsed;
	try {
		parsed = JSON.parse(raw);
	} catch {
		parsed = { raw };
	}
	return { ok: res.ok, status: res.status, statusText: res.statusText, body: parsed };
}

function htmlPage(bodyInner) {
	return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>X OAuth 2.0 token helper</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    pre { background: #111; color: #e6e6e6; padding: 1rem; overflow: auto; border-radius: 8px; font-size: 13px; }
    a.button { display: inline-block; background: #1d9bf0; color: #fff; padding: 0.6rem 1.2rem; border-radius: 999px; text-decoration: none; font-weight: 600; }
    a.button:hover { filter: brightness(1.05); }
    .muted { color: #666; font-size: 14px; }
  </style>
</head>
<body>
  ${bodyInner}
</body>
</html>`;
}

/**
 * @param {http.IncomingMessage} req
 * @param {http.ServerResponse} res
 */
async function handle(req, res) {
	const u = url.parse(req.url || "", true);

	if (u.pathname === "/" && req.method === "GET") {
		res.setHeader("Content-Type", "text/html; charset=utf-8");
		res.end(
			htmlPage(`
      <h1>X OAuth 2.0 — get tokens</h1>
      <p class="muted">Callback registered in the portal must be exactly:</p>
      <pre>${REDIRECT_URI}</pre>
      <p><a class="button" href="/start">Sign in with X</a></p>
      <p><a class="button" href="/send-dm">Send 1:1 DM</a> <span class="muted">→ user <code>${DM_RECIPIENT_USER_ID || "(set X_DM_RECIPIENT_USER_ID)"}</code></span></p>
      <p><a class="button" href="/verify-token">Verify Bearer token</a> <span class="muted">→ <code>GET /2/users/me</code> (confirms token matches portal / not expired)</span></p>
      <p><a class="button" href="/refresh-token">Refresh access token</a> <span class="muted">→ uses <code>X_REFRESH_TOKEN</code> ${REFRESH_TOKEN ? "(set)" : "(missing — paste from authorize callback JSON)"}</span></p>
      <p class="muted">Scopes: <code>${SCOPES.replace(/ /g, ", ")}</code></p>
    `),
		);
		return;
	}

	if (u.pathname === "/start" && req.method === "GET") {
		const { verifier, challenge } = newPkcePair();
		const state = base64url(crypto.randomBytes(16));
		session = { verifier, challenge, state };

		const params = new URLSearchParams({
			response_type: "code",
			client_id: CLIENT_ID,
			redirect_uri: REDIRECT_URI,
			scope: SCOPES,
			state,
			code_challenge: challenge,
			code_challenge_method: "S256",
		});

		res.writeHead(302, { Location: `${AUTH_URL}?${params.toString()}` });
		res.end();
		return;
	}

	if (u.pathname === "/verify-token" && req.method === "GET") {
		if (!ACCESS_TOKEN) {
			res.statusCode = 400;
			res.setHeader("Content-Type", "application/json; charset=utf-8");
			res.end(
				JSON.stringify({
					error: "Set X_ACCESS_TOKEN in .env for this route.",
				}),
			);
			return;
		}
		const result = await verifyAccessTokenUser();
		res.setHeader("Content-Type", "application/json; charset=utf-8");
		res.statusCode = result.ok
			? 200
			: result.status >= 400 && result.status < 600
				? result.status
				: 502;
		res.end(
			JSON.stringify(
				{
					hint: "If expired, try GET /refresh-token with X_REFRESH_TOKEN (offline.access), or Sign in again.",
					dm_host: DM_HOST,
					...result,
				},
				null,
				2,
			),
		);
		return;
	}

	if (u.pathname === "/send-dm" && req.method === "GET") {
		if (!ACCESS_TOKEN || !DM_RECIPIENT_USER_ID || !DM_MESSAGE_TEXT) {
			res.statusCode = 400;
			res.setHeader("Content-Type", "application/json; charset=utf-8");
			res.end(
				JSON.stringify({
					error:
						"Set X_ACCESS_TOKEN, X_DM_RECIPIENT_USER_ID, and X_DM_MESSAGE_TEXT in .env.",
				}),
			);
			return;
		}
		const result = await sendOneToOneDm();
		res.setHeader("Content-Type", "application/json; charset=utf-8");
		res.statusCode = result.ok ? 200 : result.status >= 400 && result.status < 600 ? result.status : 502;
		res.end(
			JSON.stringify(
				{
					endpoint: "POST /2/dm_conversations/with/:participant_id/messages",
					recipient_user_id: DM_RECIPIENT_USER_ID,
					...result,
				},
				null,
				2,
			),
		);
		return;
	}

	if (u.pathname === "/refresh-token" && req.method === "GET") {
		if (!REFRESH_TOKEN) {
			res.statusCode = 400;
			res.setHeader("Content-Type", "application/json; charset=utf-8");
			res.end(
				JSON.stringify({
					error:
						"Set X_REFRESH_TOKEN in .env (from token JSON after authorize; requires offline.access).",
				}),
			);
			return;
		}
		const result = await refreshAccessToken();
		res.setHeader("Content-Type", "application/json; charset=utf-8");
		res.statusCode = result.ok
			? 200
			: result.status >= 400 && result.status < 600
				? result.status
				: 502;
		res.end(
			JSON.stringify(
				{
					endpoint: "POST /2/oauth2/token (grant_type=refresh_token)",
					hint: "Copy access_token → X_ACCESS_TOKEN; if body includes refresh_token, replace X_REFRESH_TOKEN too (rotation).",
					...result,
				},
				null,
				2,
			),
		);
		return;
	}

	if (u.pathname === "/callback" && req.method === "GET") {
		const q = u.query;
		const code = typeof q.code === "string" ? q.code : null;
		const state = typeof q.state === "string" ? q.state : null;
		const err = typeof q.error === "string" ? q.error : null;

		if (err) {
			res.statusCode = 400;
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			res.end(
				htmlPage(
					`<h1>OAuth error</h1><pre>${err}\n${typeof q.error_description === "string" ? q.error_description : ""}</pre><p><a href="/">Home</a></p>`,
				),
			);
			return;
		}

		if (!code || !state || !session || state !== session.state) {
			res.statusCode = 400;
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			res.end(
				htmlPage(
					`<h1>Invalid callback</h1><p>Missing code/state or state mismatch. Start again from <a href="/">home</a>.</p>`,
				),
			);
			return;
		}

		const body = new URLSearchParams({
			grant_type: "authorization_code",
			code,
			redirect_uri: REDIRECT_URI,
			code_verifier: session.verifier,
		});

		const tokenRes = await fetch(TOKEN_URL, {
			method: "POST",
			headers: {
				"Content-Type": "application/x-www-form-urlencoded",
				Authorization: basicAuthHeader(),
			},
			body: body.toString(),
		});

		const rawText = await tokenRes.text();
		/** @type {unknown} */
		let json;
		try {
			json = JSON.parse(rawText);
		} catch {
			json = { raw: rawText };
		}

		session = null;

		if (!tokenRes.ok) {
			res.statusCode = 500;
			res.setHeader("Content-Type", "text/html; charset=utf-8");
			res.end(
				htmlPage(
					`<h1>Token exchange failed</h1><pre>${tokenRes.statusText}\n${typeof json === "object" && json !== null ? JSON.stringify(json, null, 2) : rawText}</pre><p><a href="/">Retry</a></p>`,
				),
			);
			return;
		}

		res.setHeader("Content-Type", "text/html; charset=utf-8");
		res.end(
			htmlPage(
				`<h1>Tokens</h1><p>Copy these into your app or env. Keep them secret.</p><pre>${JSON.stringify(json, null, 2)}</pre><p class="muted">If <code>refresh_token</code> is missing, add scope <code>offline.access</code> in the developer portal / SCOPES and re-authorize.</p><p><a href="/">Again</a></p>`,
			),
		);
		return;
	}

	res.statusCode = 404;
	res.end("Not found");
}

http.createServer((req, res) => {
	handle(req, res).catch((e) => {
		console.error(e);
		res.statusCode = 500;
		res.setHeader("Content-Type", "text/plain");
		res.end(String(e));
	});
}).listen(PORT, "127.0.0.1", () => {
	if (!CLIENT_ID || !CLIENT_SECRET) {
		console.error(
			"Set X_CLIENT_ID and X_CLIENT_SECRET in .env (same folder as server.mjs).",
		);
		process.exit(1);
	}
	console.log(`Open http://127.0.0.1:${PORT}`);
	console.log(`Callback URL (must match developer portal): ${REDIRECT_URI}`);
});
