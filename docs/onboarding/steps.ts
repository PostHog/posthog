import { ReactNode } from 'react'

export interface StepDefinition {
    title: string
    badge?: 'required' | 'recommended' | 'optional'
    content: ReactNode
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
