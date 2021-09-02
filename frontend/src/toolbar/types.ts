import { ActionStepType, ActionType, ElementType } from '~/types'
import { NamePath, StoreValue } from 'rc-field-form/es/interface'

export type ElementsEventType = {
    count: number
    elements: ElementType[]
    hash: string
}

export type TourType = {
    id: string
    created_at: string
    name: string
    cohort: number | string
    start_url: string
    team_id: number
    delay_ms: number
    is_active: boolean
    steps: TourStepType[]
}

export type TourStepEnum = 'Tooltip' | 'Modal' | 'Beacon'

export type TourStepType = {
    id?: number | string
    type?: TourStepEnum
    html_el?: string
    tooltip_title?: string
    tooltip_text?: string
    is_completed?: boolean
    is_new_step?: boolean
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
    count?: number
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

export interface AntdFieldData {
    touched?: boolean
    validating?: boolean
    errors?: string[]
    value?: StoreValue
    name: NamePath
}
