import { IconX } from '@posthog/icons'
import type { LemonMenuItem } from '@posthog/lemon-ui'

import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { NotebookNodeType } from '../types'

export function getCustomerProfileRemoveMenuItem(nodeType: NotebookNodeType): LemonMenuItem | null {
    const mountedCustomerProfileLogic = customerProfileLogic.findMounted()

    if (!mountedCustomerProfileLogic) {
        return null
    }

    return {
        label: 'Remove',
        onClick: () => mountedCustomerProfileLogic.actions.removeNode(nodeType),
        sideIcon: <IconX />,
        status: 'danger',
    }
}
