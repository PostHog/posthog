import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { pluralize } from 'lib/utils'

import { PersonType } from '~/types'

import { mergeSplitPersonLogic } from './mergeSplitPersonLogic'

export function MergeSplitPerson({ person }: { person: PersonType }): JSX.Element {
    const logicProps = { person }
    const { executedLoading } = useValues(mergeSplitPersonLogic(logicProps))
    const { execute, cancel } = useActions(mergeSplitPersonLogic(logicProps))

    return (
        <LemonModal
            isOpen
            width="40rem"
            title="Split persons"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton onClick={cancel} disabledReason={executedLoading && 'Splitting the user'}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={execute} loading={executedLoading}>
                        Split persons
                    </LemonButton>
                </div>
            }
            onClose={cancel}
        >
            {person.distinct_ids.length < 2 ? (
                'Only persons with more than two distinct IDs can be split.'
            ) : (
                <BindLogic logic={mergeSplitPersonLogic} props={logicProps}>
                    <SplitPerson />
                </BindLogic>
            )}
        </LemonModal>
    )
}

function SplitPerson(): JSX.Element | null {
    const { person, selectedPersonToAssignSplit, executedLoading } = useValues(mergeSplitPersonLogic)
    const { setSelectedPersonToAssignSplit } = useActions(mergeSplitPersonLogic)

    if (!person) {
        return null
    }

    const options = person.distinct_ids.map((distinctId: string) => ({
        label: distinctId,
        value: distinctId,
    }))

    return (
        <>
            <p>This will split all Distinct IDs for this person into unique persons.</p>
            <p>
                You can select a distinct ID for which all the current properties will be assigned (<i>optional</i>).
                All other new users will start without any properties.
            </p>
            <LemonSelect
                fullWidth
                options={options}
                placeholder="Select a distinct ID to which to assign all properties (optional)"
                disabledReason={executedLoading && 'Splitting user'}
                value={selectedPersonToAssignSplit}
                onChange={(value) => setSelectedPersonToAssignSplit(value as string)}
            />
            <LemonBanner type="warning" className="mt-4">
                This will create <strong>{person.distinct_ids.length - 1}</strong>{' '}
                {pluralize(person.distinct_ids.length - 1, 'new person', undefined, false)}. This might change the
                numbers in your charts, even historically. Please be certain.
            </LemonBanner>
        </>
    )
}
