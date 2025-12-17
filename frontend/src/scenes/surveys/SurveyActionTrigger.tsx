import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ActionType } from '~/types'

import { surveyLogic } from './surveyLogic'

export function SurveyActionTrigger(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <LemonField.Pure
            label="User performs actions"
            info="These actions are only observed in the current user session. Requires at least posthog-js v1.301.0, and is supported only for web surveys."
        >
            <EventSelect
                filterGroupTypes={[TaxonomicFilterGroupType.Actions]}
                onItemChange={(items: ActionType[]) => {
                    setSurveyValue('conditions', {
                        ...survey.conditions,
                        actions: {
                            values: items.map((e) => {
                                return { id: e.id, name: e.name }
                            }),
                        },
                    })
                }}
                selectedItems={
                    survey.conditions?.actions?.values && survey.conditions?.actions?.values.length > 0
                        ? survey.conditions?.actions?.values
                        : []
                }
                selectedEvents={survey.conditions?.actions?.values?.map((v) => v.name) ?? []}
                addElement={
                    <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
                        Add action
                    </LemonButton>
                }
            />
        </LemonField.Pure>
    )
}
