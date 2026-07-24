import { COOKIE_BANNER_ART } from './art'
import type { CookieBannerAppearanceApi } from './generated/api.schemas'

// A React re-render of the banner built in products/cookie_banner/backend/site_app_js.py —
// keep markup and styling in sync with the runtime when changing either.
export function CookieBannerPreview({ appearance }: { appearance: Required<CookieBannerAppearanceApi> }): JSX.Element {
    const artSvg = COOKIE_BANNER_ART[appearance.artStyle]
    const isBar = appearance.position === 'bottom-bar'

    const banner = (
        <div
            className={`pointer-events-none absolute bottom-4 rounded border shadow-md p-4 text-sm ${
                isBar
                    ? 'left-0 right-0 bottom-0 rounded-none flex items-center gap-4'
                    : appearance.position === 'bottom-left'
                      ? 'left-4 max-w-90'
                      : 'right-4 max-w-90'
            }`}
            style={{ backgroundColor: appearance.backgroundColor, color: appearance.textColor }}
        >
            {artSvg ? (
                <div
                    className={isBar ? 'shrink-0' : 'mb-2'}
                    // Static app-owned SVG markup, never user input
                    dangerouslySetInnerHTML={{ __html: artSvg }}
                />
            ) : null}
            <div className={isBar ? 'flex-1' : ''}>
                <p className="font-semibold text-base m-0 mb-1">{appearance.title}</p>
                <p className={isBar ? 'm-0' : 'm-0 mb-3'}>{appearance.description}</p>
            </div>
            {/* Buttons and the powered-by notice share a wrapper so the notice always sits
                underneath the buttons, including in the bottom-bar row layout */}
            <div className="shrink-0">
                <div className="flex gap-2">
                    <button
                        type="button"
                        className="rounded border-0 px-3.5 py-2 font-semibold cursor-pointer"
                        style={{ backgroundColor: appearance.buttonColor, color: appearance.buttonTextColor }}
                    >
                        {appearance.acceptButtonText}
                    </button>
                    <button
                        type="button"
                        className="rounded bg-transparent border px-3.5 py-2 font-semibold cursor-pointer"
                        style={{ color: appearance.textColor, borderColor: appearance.textColor }}
                    >
                        {appearance.declineButtonText}
                    </button>
                </div>
                {!appearance.whiteLabel && (
                    <div className={`text-[11px] opacity-65 ${isBar ? 'mt-1.5' : 'mt-2.5'}`}>
                        <span className="underline">Powered by PostHog</span>
                    </div>
                )}
            </div>
        </div>
    )

    return (
        <div className="relative h-80 rounded border bg-surface-secondary overflow-hidden">
            <div className="absolute inset-0 flex items-center justify-center text-muted text-xs">Your website</div>
            {banner}
        </div>
    )
}
