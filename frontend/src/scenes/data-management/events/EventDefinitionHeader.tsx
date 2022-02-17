import { EventDefinition } from '~/types'
import {
    AutocaptureIcon,
    PageleaveIcon,
    PageviewIcon,
    UnverifiedEventStack,
    VerifiedEventStack,
} from 'lib/components/icons'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import React from 'react'

export function getEventDefinitionIcon(definition: EventDefinition): JSX.Element {
    if (definition.name === '$pageview') {
        return <PageviewIcon className="taxonomy-icon taxonomy-icon-verified" />
    }
    if (definition.name === '$pageleave') {
        return <PageleaveIcon className="taxonomy-icon taxonomy-icon-verified" />
    }
    if (definition.name === '$autocapture') {
        return <AutocaptureIcon className="taxonomy-icon taxonomy-icon-verified" />
    }
    if (definition.verified || !!keyMapping.event[definition.name]) {
        return <VerifiedEventStack className="taxonomy-icon taxonomy-icon-verified" />
    }
    return <UnverifiedEventStack className="taxonomy-icon taxonomy-icon-muted" />
}
