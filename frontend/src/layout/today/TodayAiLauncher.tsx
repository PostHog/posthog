import type { TodayAiLauncherVariant } from './todayContextPanelLogic'

const BUBBLE = 'M8 4h16a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H14l-6 5v-5a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4z'

interface TodayAiLauncherProps {
    variant: TodayAiLauncherVariant
}

export function TodayAiLauncher({ variant }: TodayAiLauncherProps): JSX.Element {
    return (
        <span className="TodayAiLauncher" data-variant={variant}>
            <span className="TodayAiLauncher__face">
                {variant === 'bars' && (
                    <svg className="TodayAiLauncher__bars" viewBox="0 0 26 16" aria-hidden>
                        <path d="M5 1h4L5 15H1z" />
                        <path d="M13 1h4l-4 14H9z" />
                        <path d="M21 1h4l-4 14h-4z" />
                    </svg>
                )}
                {variant === 'sticker' && (
                    <svg className="TodayAiLauncher__sticker" viewBox="0 0 32 28" aria-hidden>
                        <path className="TodayAiLauncher__sticker-edge" d={BUBBLE} />
                        <path className="TodayAiLauncher__sticker-ink" d={BUBBLE} />
                    </svg>
                )}
                {variant === 'chunky' && (
                    <span className="TodayAiLauncher__dots">
                        <span />
                        <span />
                        <span />
                    </span>
                )}
                {variant === 'window' && (
                    <>
                        <span className="TodayAiLauncher__titlebar">
                            <span />
                            <span />
                            <span />
                        </span>
                        <span className="TodayAiLauncher__caret" />
                    </>
                )}
            </span>
        </span>
    )
}
