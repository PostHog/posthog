import { SceneExport } from 'scenes/sceneTypes'

import { dataModelSceneLogic } from './dataModelSceneLogic'
import NodeCanvasWithTable from './NodeCanvasWithTable'

export const scene: SceneExport = {
    component: DataModelScene,
    logic: dataModelSceneLogic,
}

const nodes = [
    {
        nodeId: 'posthog',
        name: 'PostHog',
        leaf: ['schema'],
    },
    {
        nodeId: 'stripe',
        name: 'Stripe',
        leaf: ['stripe-invoice', 'stripe-customer', 'stripe-account'],
    },
    {
        nodeId: 'stripe-invoice',
        name: 'Stripe invoice',
        leaf: ['stripe-view'],
    },
    {
        nodeId: 'stripe-view',
        name: 'Stripe view',
        leaf: ['tax_code'],
    },
    {
        nodeId: 'stripe-account',
        name: 'Stripe account',
        leaf: ['account_size', 'customer_email', 'stripe-view'],
    },
]

export function DataModelScene(): JSX.Element {
    const fixedFields = [
        { column: 'id', type: 'integer' },
        { column: 'name', type: 'string' },
        { column: 'email', type: 'string' },
        { column: 'created_at', type: 'datetime' },
        { column: 'is_active', type: 'boolean' },
        { column: 'properties', type: 'json' },
    ]

    const joinedFields = [
        { nodeId: 'customer_email', type: 'string', table: 'prod_stripe_invoice' },
        { nodeId: 'account_size', type: 'string', table: 'prod_stripe_invoice' },
        { nodeId: 'tax_code', type: 'string', table: 'prod_stripe_customer' },
        { nodeId: 'location', type: 'string', table: 'prod_stripe_account' },
        { nodeId: 'another_column', type: 'string', table: 'prod_stripe_account' },
        { nodeId: 'another_column_2', type: 'string', table: 'prod_stripe_account' },
    ]

    return (
        <NodeCanvasWithTable nodes={nodes} fixedFields={fixedFields} joinedFields={joinedFields} tableName="person" />
    )
}
