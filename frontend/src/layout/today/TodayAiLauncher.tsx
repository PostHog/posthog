import type { TodayAiLauncherVariant } from './todayContextPanelLogic'

interface TodayAiLauncherProps {
    variant: TodayAiLauncherVariant
}

export function TodayAiLauncher({ variant }: TodayAiLauncherProps): JSX.Element {
    return (
        <span className="TodayAiLauncher" data-variant={variant}>
            {variant === 'island' && <span className="TodayAiLauncher__light" />}
            {variant === 'grip' && <span className="TodayAiLauncher__ribs" />}
            {variant === 'riso' && <span className="TodayAiLauncher__paper" />}
            {variant === 'mac' && (
                <span className="TodayAiLauncher__face">
                    <span />
                    <span />
                    <span />
                </span>
            )}
        </span>
    )
}
