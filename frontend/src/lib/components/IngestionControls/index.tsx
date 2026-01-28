import { BindLogic } from 'kea'
import { PropsWithChildren } from 'react'

import { MatchTypeSelect, MatchTypeTag } from './TriggerMatchChoice'
import { IngestionControlsLogicProps, ingestionControlsLogic } from './ingestionControlsLogic'
import { EventTrigger, EventTriggerSelect } from './triggers/EventTrigger'
import FlagTrigger from './triggers/FlagTrigger'
import { FlagTriggerSelector } from './triggers/FlagTrigger/Selector'
import { FlagTriggerVariantSelector } from './triggers/FlagTrigger/VariantSelector'
import { MinDurationTrigger } from './triggers/MinDuration'
import { SamplingTrigger } from './triggers/Sampling'
import { UrlConfig } from './triggers/UrlConfig'

const IngestionControls = ({ children, ...props }: PropsWithChildren<IngestionControlsLogicProps>): JSX.Element => {
    return (
        <BindLogic logic={ingestionControlsLogic} props={props}>
            {children}
        </BindLogic>
    )
}

IngestionControls.UrlConfig = UrlConfig
IngestionControls.MatchTypeSelect = MatchTypeSelect
IngestionControls.MatchTypeTag = MatchTypeTag
IngestionControls.EventTrigger = EventTrigger
IngestionControls.EventTriggerSelect = EventTriggerSelect
IngestionControls.SamplingTrigger = SamplingTrigger
IngestionControls.MinDuration = MinDurationTrigger

IngestionControls.FlagTrigger = FlagTrigger
IngestionControls.FlagSelector = FlagTriggerSelector
IngestionControls.FlagVariantSelector = FlagTriggerVariantSelector

export default IngestionControls
