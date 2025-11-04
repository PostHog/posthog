import { ActionStepType, ActionType, ElementType, Experiment } from '~/types'

import { SelectorQualityResult } from './utils/selectorQuality'

export type ElementsEventType = {
    count: number
    elements: ElementType[]
    hash: string
    type: '$autocapture' | '$rageclick'
}

export type HeatmapResponseType = {
    results: (
        | {
              count: number
              pointer_relative_x: number
              pointer_target_fixed: boolean
              pointer_y: number
          }
        | {
              scroll_depth_bucket: number
              bucket_count: number
              cumulative_count: number
          }
    )[]
}

export type HeatmapElement = {
    count: number
    xPercentage: number
    targetFixed: boolean
    y: number
}

export interface CountedHTMLElement {
    count: number // total of types of clicks
    clickCount: number // autocapture clicks
    rageclickCount: number
    deadclickCount: number
    element: HTMLElement
    hash: string
    selector: string
    position?: number
    actionStep?: ActionStepType
    type: '$autocapture' | '$rageclick' | '$dead_click'
    // whether the browser reports this element as visible
    visible?: boolean
    rect?: ElementRect
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
    deadclickCount?: number
    position?: number
    apparentZIndex?: number
    visible?: boolean
    actionStep?: ActionStepType
    selectorQuality?: SelectorQualityResult | null
    actions?: ActionElementWithMetadata[]
}

export interface ActionElementWithMetadata extends ElementWithMetadata {
    action: ActionType
    step?: ActionStepType
}

export type ActionDraftType = Omit<ActionType, 'id' | 'created_at' | 'created_by'>

export type WebExperimentDraftType = Omit<
    Experiment,
    | 'id'
    | 'created_at'
    | 'created_by'
    | 'feature_flag_key'
    | 'filters'
    | 'metrics'
    | 'metrics_secondary'
    | 'primary_metrics_ordered_uuids'
    | 'secondary_metrics_ordered_uuids'
    | 'saved_metrics_ids'
    | 'saved_metrics'
    | 'parameters'
    | 'secondary_metrics'
    | 'updated_at'
    | 'user_access_level'
>

export interface WebExperimentForm extends WebExperimentDraftType {
    variants: Record<string, WebExperimentVariant>
    original_html_state?: Record<string, any>
}

export interface ActionStepForm extends ActionStepType {
    href_selected?: boolean
    text_selected?: boolean
    selector_selected?: boolean
    url_selected?: boolean
}

export interface ActionForm extends ActionDraftType {
    steps?: ActionStepForm[]
}

export type WebExperimentUrlMatchType = 'regex' | 'not_regex' | 'exact' | 'is_not' | 'icontains' | 'not_icontains'

export interface WebExperiment extends Experiment {
    variants: Record<string, WebExperimentVariant>
}

export interface WebExperimentVariant {
    is_new?: boolean
    conditions?: {
        url?: string
        urlMatchType?: WebExperimentUrlMatchType
        utm: {
            utm_source?: string
            utm_medium?: string
            utm_campaign?: string
            utm_term?: string
        }
    } | null
    transforms: WebExperimentTransform[]
    rollout_percentage?: number
}

export interface WebExperimentTransform {
    selector?: string
    attributes?: {
        attribute_name: string
        attribute_value: string
    }[]
    text?: string
    html?: string
    imgUrl?: string
    css?: string | null
}
