import { ActionStepType, ActionType, ElementType } from '~/types'

export type ElementsEventType = {
    count: number
    elements: ElementType[]
    hash: string
}

export interface CountedHTMLElement {
    count: number
    element: HTMLElement
    hash: string
    selector: string
    position?: number
    actionStep?: ActionStepType
}

export interface ElementWithMetadata {
    element: HTMLElement
    rect?: DOMRect
    index?: number
}

export interface ActionElementWithMetadata extends ElementWithMetadata {
    action?: ActionType
    step?: ActionStepType
}

export type BoxColor = {
    backgroundBlendMode: string
    background: string
    boxShadow: string
}

export interface ActionStepForm extends ActionStepType {
    href_selected?: boolean
    text_selected?: boolean
    selector_selected?: boolean
    url_selected?: boolean
}

export interface ActionForm extends ActionType {
    steps?: ActionStepForm[]
}
