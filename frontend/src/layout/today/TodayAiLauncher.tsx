import * as sittingHoggie from '@posthog/brand/hoggies/png/sitting'

import { Logomark } from 'lib/brand'
import { pngHoggie } from 'lib/brand/hoggies'

import type { TodayAiLauncherVariant } from './todayContextPanelLogic'

const HedgehogSitting = pngHoggie(sittingHoggie)

interface TodayAiLauncherProps {
    variant: TodayAiLauncherVariant
}

export function TodayAiLauncher({ variant }: TodayAiLauncherProps): JSX.Element {
    return (
        <span className="TodayAiLauncher" data-variant={variant}>
            {variant === 'peek' && <HedgehogSitting className="TodayAiLauncher__hoggie" />}
            <span className="TodayAiLauncher__face">
                {variant !== 'peek' && (
                    <Logomark
                        variant={variant === 'chunky' ? 'mono' : variant === 'island' ? 'print' : 'gradient'}
                        className="TodayAiLauncher__mark"
                    />
                )}
            </span>
        </span>
    )
}
