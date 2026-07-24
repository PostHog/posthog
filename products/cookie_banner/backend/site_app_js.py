"""Static JS runtime for the cookie banner, delivered through the site-apps channel in remote config.

The banner renders inside a Shadow DOM on the customer's site, wires consent into
posthog-js (`opt_in_capturing` / `opt_out_capturing`), and dispatches a `posthog:consent`
CustomEvent so customers can gate their other scripts on the visitor's choice.

The in-app live preview (products/cookie_banner/frontend/CookieBannerPreview.tsx) is a
React re-render of this markup — keep the two in sync when changing structure or styles.

Payload size matters: this JS ships inline in every /array/{token}/config.js response
for the team. Keep the runtime plus art under ~10 KB and never embed raster images.
"""

import json
from typing import Any

# Art is server-owned static markup (never user input) so it is safe to inject via
# innerHTML inside the shadow root. All user-provided text is set via textContent.
_POSTHOG_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 52 28" aria-hidden="true" width="52"><g><path fill="url(#phcb-p6)" d="M10.74 7.16 4.54.8A2.66 2.66 0 0 0 0 2.66V7.5l10.74 11.18z"/><path fill="url(#phcb-p7)" d="M9.19 28h1.55v-9.32L0 7.5v10.73z"/><path fill="url(#phcb-p8)" d="M0 25.41A2.6 2.6 0 0 0 2.58 28H9.2L0 18.23z"/></g><g><path fill="url(#phcb-p3)" d="M10.74 2.66v4.5l11.22 11.52V7.63L15.3.8a2.66 2.66 0 0 0-4.56 1.86"/><path fill="url(#phcb-p4)" d="M10.74 28h8.96l-8.96-9.32z"/><path fill="url(#phcb-p5)" d="M10.74 7.16v11.52L19.7 28h2.26v-9.32z"/></g><g><path fill="url(#phcb-p0)" d="M21.96 2.67v4.96l11.3 11.6h.02V7.75L26.63.85a2.8 2.8 0 0 0-2-.85 2.67 2.67 0 0 0-2.67 2.67"/><path fill="url(#phcb-p1)" d="M21.96 7.63v11.05L31.03 28h2.25v-8.75z"/><path fill="url(#phcb-p2)" d="M21.96 28h9.07l-9.07-9.32z"/></g><path fill="#111" d="M51.66 25.22A1.9 1.9 0 0 0 50 23.33l-.34-.04c-1-.13-1.94-.6-2.65-1.33L33.28 7.75V28H49a2.66 2.66 0 0 0 2.67-2.67zM39.2 23.54h-.09a1.78 1.78 0 1 1 .1 0"/><defs><linearGradient id="phcb-p0" x1="21.96" x2="33.28" y1="9.62" y2="9.62" gradientUnits="userSpaceOnUse"><stop stop-color="#ffd849"/><stop offset=".96" stop-color="#fbae01"/></linearGradient><linearGradient id="phcb-p1" x1="21.96" x2="33.28" y1="17.81" y2="17.81" gradientUnits="userSpaceOnUse"><stop stop-color="#ffb700"/><stop offset="1" stop-color="#f9aa01"/></linearGradient><linearGradient id="phcb-p2" x1="21.96" x2="31.03" y1="23.34" y2="23.34" gradientUnits="userSpaceOnUse"><stop stop-color="#ff9500"/><stop offset="1" stop-color="#f8aa00"/></linearGradient><linearGradient id="phcb-p3" x1="10.74" x2="21.96" y1="9.34" y2="9.34" gradientUnits="userSpaceOnUse"><stop stop-color="#ff651e"/><stop offset="1" stop-color="#e4400a"/></linearGradient><linearGradient id="phcb-p4" x1="10.74" x2="19.7" y1="23.34" y2="23.34" gradientUnits="userSpaceOnUse"><stop stop-color="#c42c00"/><stop offset="1" stop-color="#d63600"/></linearGradient><linearGradient id="phcb-p5" x1="10.74" x2="21.96" y1="17.58" y2="17.58" gradientUnits="userSpaceOnUse"><stop stop-color="#ef3c00"/><stop offset="1" stop-color="#d63601"/></linearGradient><linearGradient id="phcb-p6" x1="0" x2="10.74" y1="9.34" y2="9.34" gradientUnits="userSpaceOnUse"><stop stop-color="#3f80ff"/><stop offset="1" stop-color="#084fe0"/></linearGradient><linearGradient id="phcb-p7" x1="0" x2="10.74" y1="17.75" y2="17.75" gradientUnits="userSpaceOnUse"><stop stop-color="#0255ff"/><stop offset="1" stop-color="#0145d2"/></linearGradient><linearGradient id="phcb-p8" x1="0" x2="9.19" y1="23.11" y2="23.11" gradientUnits="userSpaceOnUse"><stop stop-color="#0041c6"/><stop offset="1" stop-color="#0045d0"/></linearGradient></defs></svg>"""

_HEDGEHOG_WAVE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 56" aria-hidden="true" width="52"><path fill="#54524d" d="M6 50 L10 32 L16 36 L18 20 L24 26 L30 10 L34 22 L42 14 L44 26 L52 22 L52 32 L58 50 Z"/><path fill="#f7e3c3" d="M34 28 Q48 26 58 36 Q62 40 60 45 Q58 50 50 50 L30 50 Q26 44 28 38 Q30 31 34 28 Z"/><circle cx="46" cy="37" r="2" fill="#2d2a26"/><circle cx="59" cy="41" r="2.5" fill="#2d2a26"/><path fill="none" stroke="#2d2a26" stroke-width="1.5" stroke-linecap="round" d="M52 44 Q55 46 58 44"/><path fill="none" stroke="#f7e3c3" stroke-width="4" stroke-linecap="round" d="M32 46 C24 44 20 38 22 30"/><ellipse cx="38" cy="51" rx="4" ry="2.5" fill="#2d2a26"/><ellipse cx="50" cy="51" rx="4" ry="2.5" fill="#2d2a26"/></svg>"""

_HEDGEHOG_HEART_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 56" aria-hidden="true" width="52"><path fill="#54524d" d="M6 50 L10 32 L16 36 L18 20 L24 26 L30 10 L34 22 L42 14 L44 26 L52 22 L52 32 L58 50 Z"/><path fill="#f7e3c3" d="M34 28 Q48 26 58 36 Q62 40 60 45 Q58 50 50 50 L30 50 Q26 44 28 38 Q30 31 34 28 Z"/><circle cx="46" cy="37" r="2" fill="#2d2a26"/><circle cx="59" cy="41" r="2.5" fill="#2d2a26"/><path fill="none" stroke="#2d2a26" stroke-width="1.5" stroke-linecap="round" d="M52 44 Q55 46 58 44"/><path fill="#f54e00" d="M52 20 C48 16 44 12 48 8 C50 6 52 8 52 10 C52 8 54 6 56 8 C60 12 56 16 52 20 Z"/><ellipse cx="38" cy="51" rx="4" ry="2.5" fill="#2d2a26"/><ellipse cx="50" cy="51" rx="4" ry="2.5" fill="#2d2a26"/></svg>"""

COOKIE_BANNER_ART: dict[str, str] = {
    "posthog-logo": _POSTHOG_LOGO_SVG,
    "hedgehog-wave": _HEDGEHOG_WAVE_SVG,
    "hedgehog-heart": _HEDGEHOG_HEART_SVG,
}

_BANNER_CSS = """
.banner {
    position: fixed;
    z-index: 2147483000;
    box-sizing: border-box;
    max-width: 360px;
    padding: 16px;
    border-radius: 8px;
    border: 1px solid rgba(0, 0, 0, 0.1);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.4;
    text-align: left;
}
.banner.bottom-right { right: 16px; bottom: 16px; }
.banner.bottom-left { left: 16px; bottom: 16px; }
.banner.bottom-bar { left: 0; right: 0; bottom: 0; max-width: none; border-radius: 0; display: flex; align-items: center; gap: 16px; }
.banner.bottom-bar .content { flex: 1 1 auto; }
.banner.bottom-bar .art, .banner.bottom-bar .description { margin-bottom: 0; }
.banner.bottom-bar .powered { margin-top: 0; }
.art { margin-bottom: 8px; }
.art svg { display: block; }
.title { font-weight: 600; font-size: 16px; margin: 0 0 4px; }
.description { margin: 0 0 12px; }
.actions { display: flex; gap: 8px; flex-shrink: 0; }
.actions button { cursor: pointer; border: none; border-radius: 6px; padding: 8px 14px; font: inherit; font-weight: 600; }
.actions .decline { background: transparent; border: 1px solid rgba(0, 0, 0, 0.2); }
.powered { margin-top: 10px; font-size: 11px; opacity: 0.65; flex-shrink: 0; }
.powered a { color: inherit; }
"""

_RUNTIME_JS_TEMPLATE = """function (posthog, cfg) {
    var STORAGE_KEY = '__ph_cookie_banner_consent';
    var ART = __ART__;
    var CSS = __CSS__;

    function getStoredChoice() {
        try {
            var value = window.localStorage.getItem(STORAGE_KEY);
            if (value === 'accepted' || value === 'declined') { return value; }
        } catch (e) {}
        try {
            var match = document.cookie.match(new RegExp('(?:^|; ?)' + STORAGE_KEY + '=(accepted|declined)'));
            if (match) { return match[1]; }
        } catch (e) {}
        return null;
    }

    function storeChoice(status) {
        try { window.localStorage.setItem(STORAGE_KEY, status); } catch (e) {}
        try { document.cookie = STORAGE_KEY + '=' + status + '; path=/; max-age=31536000; SameSite=Lax'; } catch (e) {}
    }

    function dispatchConsent(status, source) {
        try {
            window.dispatchEvent(new CustomEvent('posthog:consent', { detail: { status: status, source: source } }));
        } catch (e) {}
    }

    var storedChoice = getStoredChoice();
    if (storedChoice) {
        dispatchConsent(storedChoice, 'stored');
        return;
    }

    function renderBanner() {
        if (document.querySelector('[data-posthog-cookie-banner]')) { return; }
        var host = document.createElement('div');
        host.setAttribute('data-posthog-cookie-banner', '');
        var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;

        var style = document.createElement('style');
        style.textContent = CSS;
        root.appendChild(style);

        var banner = document.createElement('div');
        banner.className = 'banner ' + cfg.position;
        banner.style.backgroundColor = cfg.backgroundColor;
        banner.style.color = cfg.textColor;
        banner.setAttribute('role', 'dialog');
        banner.setAttribute('aria-label', cfg.title);

        if (ART[cfg.artStyle]) {
            var art = document.createElement('div');
            art.className = 'art';
            art.innerHTML = ART[cfg.artStyle];
            banner.appendChild(art);
        }

        var content = document.createElement('div');
        content.className = 'content';
        var title = document.createElement('p');
        title.className = 'title';
        title.textContent = cfg.title;
        var description = document.createElement('p');
        description.className = 'description';
        description.textContent = cfg.description;
        content.appendChild(title);
        content.appendChild(description);
        banner.appendChild(content);

        function choose(status) {
            storeChoice(status);
            try {
                if (status === 'accepted') { posthog.opt_in_capturing(); } else { posthog.opt_out_capturing(); }
            } catch (e) {}
            dispatchConsent(status, 'user');
            if (host.parentNode) { host.parentNode.removeChild(host); }
        }

        var actions = document.createElement('div');
        actions.className = 'actions';

        var accept = document.createElement('button');
        accept.className = 'accept';
        accept.type = 'button';
        accept.textContent = cfg.acceptButtonText;
        accept.style.backgroundColor = cfg.buttonColor;
        accept.style.color = cfg.buttonTextColor;
        accept.addEventListener('click', function () { choose('accepted'); });
        actions.appendChild(accept);

        var decline = document.createElement('button');
        decline.className = 'decline';
        decline.type = 'button';
        decline.textContent = cfg.declineButtonText;
        decline.style.color = cfg.textColor;
        decline.addEventListener('click', function () { choose('declined'); });
        actions.appendChild(decline);

        banner.appendChild(actions);

        if (!cfg.whiteLabel) {
            var powered = document.createElement('div');
            powered.className = 'powered';
            var poweredLink = document.createElement('a');
            poweredLink.href = 'https://posthog.com';
            poweredLink.target = '_blank';
            poweredLink.rel = 'noopener';
            poweredLink.textContent = 'Powered by PostHog';
            powered.appendChild(poweredLink);
            banner.appendChild(powered);
        }

        root.appendChild(banner);
        document.body.appendChild(host);
    }

    if (document.body) {
        renderBanner();
    } else {
        window.addEventListener('DOMContentLoaded', renderBanner);
    }
}"""


def _runtime_js(art_style: str) -> str:
    # Only ship the one SVG the banner actually uses, to keep config.js small
    art = {art_style: COOKIE_BANNER_ART[art_style]} if art_style in COOKIE_BANNER_ART else {}
    return _RUNTIME_JS_TEMPLATE.replace("__ART__", json.dumps(art)).replace("__CSS__", json.dumps(_BANNER_CSS))


def build_cookie_banner_js(client_config: dict[str, Any]) -> str:
    """Return a siteAppsJS entry ({id, init}) matching the shape built in
    posthog/models/remote_config.py `_build_site_apps_js`."""
    runtime = _runtime_js(str(client_config.get("artStyle", "")))
    return (
        "\n{\n"
        "  id: 'cookie-banner',\n"
        f"  init: function(config) {{\n"
        f"    ({runtime})(config.posthog, {json.dumps(client_config)});\n"
        f"    config.callback(); return {{}}\n"
        f"  }}\n"
        "}"
    )
