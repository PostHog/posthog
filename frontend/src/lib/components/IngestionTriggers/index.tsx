import { BindLogic } from 'kea'
import { PropsWithChildren } from 'react'

import { MatchTypeSelect, MatchTypeTag } from './TriggerMatchChoice'
import { IngestionTriggersLogicProps, ingestionTriggersLogic } from './ingestionTriggersLogic'
import { EventTrigger, EventTriggerSelect } from './triggers/EventTrigger'
import FlagTrigger from './triggers/FlagTrigger'
import { FlagTriggerSelector } from './triggers/FlagTrigger/Selector'
import { FlagTriggerVariantSelector } from './triggers/FlagTrigger/VariantSelector'
import { MinDurationTrigger } from './triggers/MinDuration'
import { SamplingTrigger } from './triggers/Sampling'
import { UrlConfig } from './triggers/UrlConfig'

const IngestionTriggers = ({ children, ...props }: PropsWithChildren<IngestionTriggersLogicProps>): JSX.Element => {
    return (
        <BindLogic logic={ingestionTriggersLogic} props={props}>
            {children}
        </BindLogic>
    )
}

IngestionTriggers.UrlConfig = UrlConfig
IngestionTriggers.MatchTypeSelect = MatchTypeSelect
IngestionTriggers.MatchTypeTag = MatchTypeTag
IngestionTriggers.EventTrigger = EventTrigger
IngestionTriggers.EventTriggerSelect = EventTriggerSelect
IngestionTriggers.SamplingTrigger = SamplingTrigger
IngestionTriggers.MinDuration = MinDurationTrigger

IngestionTriggers.FlagTrigger = FlagTrigger
IngestionTriggers.FlagSelector = FlagTriggerSelector
IngestionTriggers.FlagVariantSelector = FlagTriggerVariantSelector

export default IngestionTriggers
