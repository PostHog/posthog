import React from 'react'
import { CreateOrganizationModal } from '~/layout/TopContent/TopSelectors'

export function Create(): JSX.Element {
    return <CreateOrganizationModal isVisible={true} />
}
