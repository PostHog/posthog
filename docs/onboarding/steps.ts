import { ReactNode } from 'react'

export interface StepDefinition {
    title: string
    badge?: 'required' | 'recommended' | 'optional'
    content: ReactNode
    subtitle?: string
    checkpoint?: boolean
}

export interface StepModifier {
    modifySteps?: (steps: StepDefinition[]) => StepDefinition[]
}

export interface StepProps {
    title: string
    subtitle?: string
    badge?: 'required' | 'recommended' | 'optional'
    checkpoint?: boolean
    docsOnly?: boolean
    children: ReactNode
}

export interface StepsProps {
    children: ReactNode
}

/** CodeBlock tab language that renders markdown prose with clickable links instead of highlighted code. */
export const PROSE_LANGUAGE = 'prose'
