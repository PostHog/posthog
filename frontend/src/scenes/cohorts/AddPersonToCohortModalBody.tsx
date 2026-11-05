import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { PersonSelectList } from './PersonSelectList'
import { SelectedPeopleList } from './SelectedPeopleList'

export function AddPersonToCohortModalBody(): JSX.Element {
    const { query, cohortPersons, personsToAddToCohort } = useValues(addPersonToCohortModalLogic)
    const { setQuery, addPerson, removePerson } = useActions(addPersonToCohortModalLogic)

    const cohortPersonsSet = useMemo(() => {
        return new Set(cohortPersons.results.map((p) => p.id).filter((id): id is string => id != null))
    }, [cohortPersons])

    return (
        <div className="flex flex-col gap-y-2">
            <PersonSelectList
                query={query}
                setQuery={setQuery}
                selectedPersons={personsToAddToCohort}
                onAddPerson={addPerson}
                onRemovePerson={removePerson}
                existingPersonsSet={cohortPersonsSet}
                dataNodeKey="addPersonToCohortModal"
                autoFocus
            />
            <SelectedPeopleList people={personsToAddToCohort} onRemove={removePerson} />
        </div>
    )
}
