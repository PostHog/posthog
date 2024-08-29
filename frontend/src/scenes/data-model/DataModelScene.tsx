import { SceneExport } from 'scenes/sceneTypes'

import { dataModelSceneLogic } from './dataModelSceneLogic'
import ScrollableDraggableCanvas from './DotGridBackground'

export const scene: SceneExport = {
    component: DataModelScene,
    logic: dataModelSceneLogic,
}

const nodes = [
    {
        id: 'posthog',
        name: 'PostHog',
        leaf: ['schema'],
    },
    {
        id: 'stripe',
        name: 'Stripe',
        leaf: ['stripe-invoice', 'stripe-customer', 'stripe-account'],
    },
    {
        id: 'stripe-invoice',
        name: 'Stripe invoice',
        leaf: ['stripe-view'],
    },
    {
        id: 'stripe-view',
        name: 'Stripe view',
        leaf: ['tax_code'],
    },
    {
        id: 'stripe-account',
        name: 'Stripe account',
        leaf: ['account_size', 'customer_email', 'stripe-view'],
    },
]

export function DataModelScene(): JSX.Element {
    return (
        <div className="w-full h-full">
            <ScrollableDraggableCanvas nodes={nodes} />
        </div>
    )
}
