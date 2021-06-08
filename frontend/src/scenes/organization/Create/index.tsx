import React, { useState } from 'react'
import { CreateOrganizationModal } from '../CreateOrganizationModal'

export function Create(): JSX.Element {
    const [isVisible, setIsVisible] = useState(true)

    return <CreateOrganizationModal isVisible={isVisible} setIsVisible={setIsVisible} />
}
