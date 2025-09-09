import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'

export function BaseCurrency({ hideTitle = false }: { hideTitle?: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <SceneSection
            hideTitleAndDescription={!newSceneLayout}
            title={!hideTitle ? 'Base currency' : undefined}
            description="PostHog will convert all currency values for the entire team to this currency before displaying them to you. If we can't properly detect your currency, we'll assume it's in this currency as well."
            className={cn(!newSceneLayout && 'gap-y-0')}
        >
            {!newSceneLayout && (
                <>
                    {!hideTitle && <h3>Base currency</h3>}
                    <p>
                        PostHog will convert all currency values for the entire team to this currency before displaying
                        them to you. If we can't properly detect your currency, we'll assume it's in this currency as
                        well.
                    </p>
                </>
            )}
            <div>
                <CurrencyDropdown
                    value={currentTeam?.base_currency || null}
                    onChange={(currency: CurrencyCode | null) => {
                        updateCurrentTeam({ base_currency: currency ?? undefined })
                    }}
                />
            </div>
        </SceneSection>
    )
}
