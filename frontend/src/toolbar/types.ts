import { ActionStepType, ActionType, ElementType } from '~/types'

export type ElementsEventType = {
    count: number
    elements: ElementType[]
    hash: string
    type: '$autocapture' | '$rageclick'
}

export interface CountedHTMLElement {
    count: number // total of types of clicks
    clickCount: number // autocapture clicks
    rageclickCount: number
    element: HTMLElement
    hash: string
    selector: string
    position?: number
    actionStep?: ActionStepType
    type: '$autocapture' | '$rageclick'
}

export interface ElementRect {
    bottom: number
    height: number
    left: number
    right: number
    top: number
    width: number
    x: number
    y: number
}
export interface ElementWithMetadata {
    element: HTMLElement
    rect?: ElementRect
    index?: number
    count?: number
    clickCount?: number
    rageclickCount?: number
    position?: number
}

export interface ActionElementWithMetadata extends ElementWithMetadata {
    action: ActionType
    step?: ActionStepType
}

export type BoxColor = {
    backgroundBlendMode: string
    background: string
    boxShadow: string
}

export type ActionDraftType = Omit<ActionType, 'id' | 'created_at' | 'created_by'>

export interface ActionStepForm extends ActionStepType {
    href_selected?: boolean
    text_selected?: boolean
    selector_selected?: boolean
    url_selected?: boolean
}

export interface ActionForm extends ActionDraftType {
    steps?: ActionStepForm[]
}
