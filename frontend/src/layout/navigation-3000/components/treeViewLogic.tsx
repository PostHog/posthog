import {
    IconBook,
    IconCursorClick,
    IconDatabase,
    IconGraph,
    IconLive,
    IconMessage,
    IconNotebook,
    IconPeople,
    IconPieChart,
    IconPlug,
    IconRewindPlay,
    IconRocket,
    IconServer,
    IconSparkles,
    IconTarget,
    IconTestTube,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'

import { InsightType, PipelineStage, ReplayTabs } from '~/types'

import type { treeViewLogicType } from './treeViewLogicType'

const debugHog1 = `#repl=%5B%7B"code"%3A"let%20query%20%3A%3D%20'select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20%5C%5C'%24pageview%5C%5C'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser'"%2C"status"%3A"success"%2C"bytecode"%3A%5B32%2C"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%5D%2C"locals"%3A%5B%5B"query"%2C1%2Cfalse%5D%5D%2C"result"%3A"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%5D%7D%7D%2C"stack"%3A%5B"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A1%2C"asyncSteps"%3A0%2C"syncDuration"%3A0%2C"maxMemUsed"%3A208%7D%7D%2C%7B"code"%3A"run(query)%5Cn"%2C"status"%3A"success"%2C"bytecode"%3A%5B36%2C0%2C2%2C"run"%2C1%2C35%5D%2C"locals"%3A%5B%5B"query"%2C1%2Cfalse%5D%5D%2C"result"%3A%7B"results"%3A%5B%5B"2025-02-10"%2C"Chrome"%2C291%5D%5D%2C"columns"%3A%5B"toDate(toStartOfDay(timestamp))"%2C"%24browser"%2C"count()"%5D%7D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C36%2C0%2C2%2C"run"%2C1%5D%7D%7D%2C"stack"%3A%5B"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C%7B"results"%3A%5B%5B"2025-02-10"%2C"Chrome"%2C291%5D%5D%2C"columns"%3A%5B"toDate(toStartOfDay(timestamp))"%2C"%24browser"%2C"count()"%5D%7D%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A3%2C"asyncSteps"%3A1%2C"syncDuration"%3A0%2C"maxMemUsed"%3A416%7D%7D%2C%7B"code"%3A"fun%20pivot(result%2C%20label%2C%20default)%20%7B%5Cn%20%20%20%20let%20dates%20%3A%3D%20arrayMap(row%20->%20row.1%2C%20result.results)%5Cn%20%20%20%20let%20columns%20%3A%3D%20%5Blabel%5D%5Cn%20%20%20%20for%20(let%20date%20in%20dates)%20%7B%20columns%20%3A%3D%20arrayPushBack(columns%2C%20date)%20%7D%5Cn%20%20%20%20let%20cache%20%3A%3D%20%7B%7D%5Cn%20%20%20%20let%20sessions%20%3A%3D%20%7B%7D%5Cn%20%20%20%20for%20(let%20row%20in%20result.results)%20%7B%5Cn%20%20%20%20%20%20%20%20cache%5Bf'%7Brow.1%7D-%7Brow.2%7D'%5D%20%3A%3D%20row.3%5Cn%20%20%20%20%20%20%20%20sessions%5Brow.2%5D%20%3A%3D%20true%5Cn%20%20%20%20%7D%5Cn%20%20%20%20let%20rows%20%3A%3D%20arrayMap(session%20->%20%7B%5Cn%20%20%20%20%20%20%20%20let%20row%20%3A%3D%20%5Bsession%5D%5Cn%20%20%20%20%20%20%20%20for%20(let%20date%20in%20dates)%20%7B%20row%20%3A%3D%20arrayPushBack(row%2C%20ifNull(cache%5Bf'%7Bdate%7D-%7Bsession%7D'%5D%2C%20default))%20%7D%5Cn%20%20%20%20%20%20%20%20return%20row%5Cn%20%20%20%20%7D%2C%20keys(sessions))%5Cn%20%20%20%20let%20table%20%3A%3D%20%7B%20'columns'%3A%20columns%2C%20'results'%3A%20rows%20%7D%5Cn%20%20%20%20return%20table%5Cn%7D"%2C"status"%3A"success"%2C"bytecode"%3A%5B52%2C"pivot"%2C3%2C0%2C274%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C1%2C43%2C1%2C36%2C3%2C36%2C5%2C2%2C"values"%2C1%2C33%2C1%2C36%2C6%2C2%2C"length"%2C1%2C31%2C36%2C8%2C36%2C7%2C16%2C40%2C25%2C36%2C6%2C36%2C7%2C45%2C37%2C9%2C36%2C4%2C36%2C9%2C2%2C"arrayPushBack"%2C2%2C37%2C4%2C36%2C7%2C33%2C1%2C6%2C37%2C7%2C39%2C-32%2C35%2C35%2C35%2C35%2C35%2C42%2C0%2C42%2C0%2C36%2C0%2C32%2C"results"%2C45%2C36%2C7%2C2%2C"values"%2C1%2C33%2C1%2C36%2C8%2C2%2C"length"%2C1%2C31%2C36%2C10%2C36%2C9%2C16%2C40%2C48%2C36%2C8%2C36%2C9%2C45%2C37%2C11%2C36%2C5%2C36%2C11%2C33%2C1%2C45%2C32%2C"-"%2C36%2C11%2C33%2C2%2C45%2C2%2C"concat"%2C3%2C36%2C11%2C33%2C3%2C45%2C46%2C36%2C6%2C36%2C11%2C33%2C2%2C45%2C29%2C46%2C36%2C9%2C33%2C1%2C6%2C37%2C9%2C39%2C-55%2C35%2C35%2C35%2C35%2C35%2C52%2C"lambda"%2C1%2C3%2C75%2C36%2C0%2C43%2C1%2C55%2C0%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C40%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C36%2C1%2C55%2C1%2C36%2C6%2C32%2C"-"%2C36%2C0%2C2%2C"concat"%2C3%2C45%2C47%2C3%2C35%2C55%2C2%2C2%2C"arrayPushBack"%2C2%2C37%2C1%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-47%2C35%2C35%2C35%2C35%2C35%2C36%2C1%2C38%2C35%2C53%2C3%2Ctrue%2C3%2Ctrue%2C5%2Ctrue%2C2%2C36%2C6%2C2%2C"keys"%2C1%2C2%2C"arrayMap"%2C2%2C32%2C"columns"%2C36%2C4%2C32%2C"results"%2C36%2C7%2C42%2C2%2C36%2C8%2C38%2C35%2C35%2C35%2C57%2C35%2C57%2C53%2C0%5D%2C"locals"%3A%5B%5B"query"%2C1%2Cfalse%5D%2C%5B"pivot"%2C1%2Cfalse%5D%5D%2C"result"%3A%7B"__hogClosure__"%3Atrue%2C"callable"%3A%7B"__hogCallable__"%3A"local"%2C"name"%3A"pivot"%2C"chunk"%3A"root"%2C"argCount"%3A3%2C"upvalueCount"%3A0%2C"ip"%3A15%7D%2C"upvalues"%3A%5B%5D%7D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C36%2C0%2C2%2C"run"%2C1%2C35%2C52%2C"pivot"%2C3%2C0%2C274%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C1%2C43%2C1%2C36%2C3%2C36%2C5%2C2%2C"values"%2C1%2C33%2C1%2C36%2C6%2C2%2C"length"%2C1%2C31%2C36%2C8%2C36%2C7%2C16%2C40%2C25%2C36%2C6%2C36%2C7%2C45%2C37%2C9%2C36%2C4%2C36%2C9%2C2%2C"arrayPushBack"%2C2%2C37%2C4%2C36%2C7%2C33%2C1%2C6%2C37%2C7%2C39%2C-32%2C35%2C35%2C35%2C35%2C35%2C42%2C0%2C42%2C0%2C36%2C0%2C32%2C"results"%2C45%2C36%2C7%2C2%2C"values"%2C1%2C33%2C1%2C36%2C8%2C2%2C"length"%2C1%2C31%2C36%2C10%2C36%2C9%2C16%2C40%2C48%2C36%2C8%2C36%2C9%2C45%2C37%2C11%2C36%2C5%2C36%2C11%2C33%2C1%2C45%2C32%2C"-"%2C36%2C11%2C33%2C2%2C45%2C2%2C"concat"%2C3%2C36%2C11%2C33%2C3%2C45%2C46%2C36%2C6%2C36%2C11%2C33%2C2%2C45%2C29%2C46%2C36%2C9%2C33%2C1%2C6%2C37%2C9%2C39%2C-55%2C35%2C35%2C35%2C35%2C35%2C52%2C"lambda"%2C1%2C3%2C75%2C36%2C0%2C43%2C1%2C55%2C0%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C40%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C36%2C1%2C55%2C1%2C36%2C6%2C32%2C"-"%2C36%2C0%2C2%2C"concat"%2C3%2C45%2C47%2C3%2C35%2C55%2C2%2C2%2C"arrayPushBack"%2C2%2C37%2C1%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-47%2C35%2C35%2C35%2C35%2C35%2C36%2C1%2C38%2C35%2C53%2C3%2Ctrue%2C3%2Ctrue%2C5%2Ctrue%2C2%2C36%2C6%2C2%2C"keys"%2C1%2C2%2C"arrayMap"%2C2%2C32%2C"columns"%2C36%2C4%2C32%2C"results"%2C36%2C7%2C42%2C2%2C36%2C8%2C38%2C35%2C35%2C35%2C57%2C35%2C57%2C53%2C0%5D%7D%7D%2C"stack"%3A%5B"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C%7B"__hogClosure__"%3Atrue%2C"callable"%3A%7B"__hogCallable__"%3A"local"%2C"name"%3A"pivot"%2C"chunk"%3A"root"%2C"argCount"%3A3%2C"upvalueCount"%3A0%2C"ip"%3A15%7D%2C"upvalues"%3A%5B%5D%7D%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A5%2C"asyncSteps"%3A1%2C"syncDuration"%3A0%2C"maxMemUsed"%3A450%7D%7D%2C%7B"code"%3A"pivot(run(query)%2C%20'Browser'%2C%200)%5Cn"%2C"status"%3A"success"%2C"bytecode"%3A%5B36%2C0%2C2%2C"run"%2C1%2C32%2C"Browser"%2C33%2C0%2C36%2C1%2C54%2C3%2C35%5D%2C"locals"%3A%5B%5B"query"%2C1%2Cfalse%5D%2C%5B"pivot"%2C1%2Cfalse%5D%5D%2C"result"%3A%7B"columns"%3A%5B"Browser"%2C"2025-02-10"%5D%2C"results"%3A%5B%5B"Chrome"%2C291%5D%5D%7D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C36%2C0%2C2%2C"run"%2C1%2C35%2C52%2C"pivot"%2C3%2C0%2C274%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C1%2C43%2C1%2C36%2C3%2C36%2C5%2C2%2C"values"%2C1%2C33%2C1%2C36%2C6%2C2%2C"length"%2C1%2C31%2C36%2C8%2C36%2C7%2C16%2C40%2C25%2C36%2C6%2C36%2C7%2C45%2C37%2C9%2C36%2C4%2C36%2C9%2C2%2C"arrayPushBack"%2C2%2C37%2C4%2C36%2C7%2C33%2C1%2C6%2C37%2C7%2C39%2C-32%2C35%2C35%2C35%2C35%2C35%2C42%2C0%2C42%2C0%2C36%2C0%2C32%2C"results"%2C45%2C36%2C7%2C2%2C"values"%2C1%2C33%2C1%2C36%2C8%2C2%2C"length"%2C1%2C31%2C36%2C10%2C36%2C9%2C16%2C40%2C48%2C36%2C8%2C36%2C9%2C45%2C37%2C11%2C36%2C5%2C36%2C11%2C33%2C1%2C45%2C32%2C"-"%2C36%2C11%2C33%2C2%2C45%2C2%2C"concat"%2C3%2C36%2C11%2C33%2C3%2C45%2C46%2C36%2C6%2C36%2C11%2C33%2C2%2C45%2C29%2C46%2C36%2C9%2C33%2C1%2C6%2C37%2C9%2C39%2C-55%2C35%2C35%2C35%2C35%2C35%2C52%2C"lambda"%2C1%2C3%2C75%2C36%2C0%2C43%2C1%2C55%2C0%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C40%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C36%2C1%2C55%2C1%2C36%2C6%2C32%2C"-"%2C36%2C0%2C2%2C"concat"%2C3%2C45%2C47%2C3%2C35%2C55%2C2%2C2%2C"arrayPushBack"%2C2%2C37%2C1%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-47%2C35%2C35%2C35%2C35%2C35%2C36%2C1%2C38%2C35%2C53%2C3%2Ctrue%2C3%2Ctrue%2C5%2Ctrue%2C2%2C36%2C6%2C2%2C"keys"%2C1%2C2%2C"arrayMap"%2C2%2C32%2C"columns"%2C36%2C4%2C32%2C"results"%2C36%2C7%2C42%2C2%2C36%2C8%2C38%2C35%2C35%2C35%2C57%2C35%2C57%2C53%2C0%2C36%2C0%2C2%2C"run"%2C1%2C32%2C"Browser"%2C33%2C0%2C36%2C1%2C54%2C3%5D%7D%7D%2C"stack"%3A%5B"select%20toDate(toStartOfDay(timestamp))%2C%20properties.%24browser%2C%20count()%20from%20events%20where%20event%20%3D%20'%24pageview'%20and%20timestamp%20>%20now()%20-%20interval%201%20week%20group%20by%20toStartOfDay(timestamp)%2C%20properties.%24browser"%2C%7B"__hogClosure__"%3Atrue%2C"callable"%3A%7B"__hogCallable__"%3A"local"%2C"name"%3A"pivot"%2C"chunk"%3A"root"%2C"argCount"%3A3%2C"upvalueCount"%3A0%2C"ip"%3A15%7D%2C"upvalues"%3A%5B%5D%7D%2C%7B"columns"%3A%5B"Browser"%2C"2025-02-10"%5D%2C"results"%3A%5B%5B"Chrome"%2C291%5D%5D%7D%5D%2C"upvalues"%3A%5B%7B"__hogUpValue__"%3Atrue%2C"id"%3A3%2C"location"%3A4%2C"closed"%3Atrue%2C"value"%3A0%7D%2C%7B"__hogUpValue__"%3Atrue%2C"id"%3A1%2C"location"%3A5%2C"closed"%3Atrue%2C"value"%3A%5B"2025-02-10"%5D%7D%2C%7B"__hogUpValue__"%3Atrue%2C"id"%3A2%2C"location"%3A7%2C"closed"%3Atrue%2C"value"%3A%7B"2025-02-10-Chrome"%3A291%7D%7D%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A239%2C"asyncSteps"%3A2%2C"syncDuration"%3A0%2C"maxMemUsed"%3A1427%7D%7D%5D&code=`

const debugHog2 = `#repl=%5B%7B"code"%3A"let%20results%20%3A%3D%20run('select%20count()%2C%20event%20from%20events%20where%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20event%20order%20by%20count()%20desc%20limit%2010')"%2C"status"%3A"success"%2C"bytecode"%3A%5B32%2C"select%20count()%2C%20event%20from%20events%20where%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20event%20order%20by%20count()%20desc%20limit%2010"%2C2%2C"run"%2C1%5D%2C"locals"%3A%5B%5B"results"%2C1%2Cfalse%5D%5D%2C"result"%3A%7B"results"%3A%5B%5B11127474%2C"%24feature_flag_called"%5D%2C%5B4818997%2C"%24exception"%5D%2C%5B4704834%2C"%24autocapture"%5D%2C%5B2846874%2C"%24pageview"%5D%2C%5B2591627%2C"query%20completed"%5D%2C%5B1890908%2C"v2%20session%20recording%20snapshots%20viewed"%5D%2C%5B1594234%2C"session%20recording%20snapshots%20v2%20loaded"%5D%2C%5B1188742%2C"time%20to%20see%20data"%5D%2C%5B1185929%2C"recording%20loaded"%5D%2C%5B1140632%2C"%24groupidentify"%5D%5D%2C"columns"%3A%5B"count()"%2C"event"%5D%7D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20count()%2C%20event%20from%20events%20where%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20event%20order%20by%20count()%20desc%20limit%2010"%2C2%2C"run"%2C1%5D%7D%7D%2C"stack"%3A%5B%7B"results"%3A%5B%5B11127474%2C"%24feature_flag_called"%5D%2C%5B4818997%2C"%24exception"%5D%2C%5B4704834%2C"%24autocapture"%5D%2C%5B2846874%2C"%24pageview"%5D%2C%5B2591627%2C"query%20completed"%5D%2C%5B1890908%2C"v2%20session%20recording%20snapshots%20viewed"%5D%2C%5B1594234%2C"session%20recording%20snapshots%20v2%20loaded"%5D%2C%5B1188742%2C"time%20to%20see%20data"%5D%2C%5B1185929%2C"recording%20loaded"%5D%2C%5B1140632%2C"%24groupidentify"%5D%5D%2C"columns"%3A%5B"count()"%2C"event"%5D%7D%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A2%2C"asyncSteps"%3A1%2C"syncDuration"%3A0%2C"maxMemUsed"%3A508%7D%7D%2C%7B"code"%3A"let%20events%20%3A%3D%20arrayMap(a%20->%20a.2%2C%20results.results)%5Cnfor%20(let%20event%20in%20events)%20%7B%5Cn%20%20let%20data%20%3A%3D%20run(f'select%20count()%2C%20toStartOfDay(timestamp)%20as%20day%20from%20events%20where%20event%20%3D%20%5C%5C'%7Bevent%7D%5C%5C'%20and%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20day%20order%20by%20day')%5Cn%20%20print(%5Cn%20%20%20%20event%2C%20%5Cn%20%20%20%20<Sparkline%20%5Cn%20%20%20%20%20%20data%3D%7BarrayMap(a%20->%20a.1%2C%20data.results)%7D%20%5Cn%20%20%20%20%20%20labels%3D%7BarrayMap(a%20->%20a.2%2C%20data.results)%7D%20type%3D'line'%20%5Cn%20%20%20%20%2F>%5Cn%20%20)%5Cn%7D%5Cnprint('We%20are%20done!')"%2C"status"%3A"success"%2C"bytecode"%3A%5B52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C1%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C91%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C32%2C"select%20count()%2C%20toStartOfDay(timestamp)%20as%20day%20from%20events%20where%20event%20%3D%20'"%2C36%2C6%2C32%2C"'%20and%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20day%20order%20by%20day"%2C2%2C"concat"%2C3%2C2%2C"run"%2C1%2C36%2C6%2C32%2C"__hx_tag"%2C32%2C"Sparkline"%2C32%2C"data"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C7%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"labels"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C7%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"type"%2C32%2C"line"%2C42%2C4%2C2%2C"print"%2C2%2C35%2C35%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-98%2C35%2C35%2C35%2C35%2C35%2C32%2C"We%20are%20done!"%2C2%2C"print"%2C1%2C35%5D%2C"locals"%3A%5B%5B"results"%2C1%2Cfalse%5D%2C%5B"events"%2C1%2Cfalse%5D%5D%2C"print"%3A%5B%5B"%24feature_flag_called"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B1472885%2C1994957%2C1944942%2C1878662%2C1543406%2C694747%2C1077544%2C520267%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"%24exception"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B527589%2C675262%2C640218%2C747226%2C746912%2C663242%2C653204%2C165293%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"%24autocapture"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B641194%2C895205%2C862215%2C837661%2C683267%2C240081%2C318824%2C226399%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"%24pageview"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B389480%2C521757%2C494655%2C483009%2C430122%2C179559%2C215435%2C132878%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"query%20completed"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B338146%2C462482%2C470546%2C451021%2C386020%2C151561%2C203235%2C128599%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"v2%20session%20recording%20snapshots%20viewed"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B237212%2C354950%2C358767%2C329124%2C279034%2C118686%2C137223%2C75906%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"session%20recording%20snapshots%20v2%20loaded"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B199196%2C300929%2C304069%2C278392%2C235441%2C98960%2C114153%2C63073%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"time%20to%20see%20data"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B160241%2C221113%2C210001%2C203252%2C172323%2C67028%2C92645%2C62136%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"recording%20loaded"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B147849%2C224946%2C225305%2C206360%2C175340%2C73833%2C86185%2C46116%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"%24groupidentify"%2C%7B"__hx_tag"%3A"Sparkline"%2C"data"%3A%5B149301%2C195489%2C203736%2C188537%2C156380%2C72987%2C106910%2C67317%5D%2C"labels"%3A%5B"2025-02-03T00%3A00%3A00-08%3A00"%2C"2025-02-04T00%3A00%3A00-08%3A00"%2C"2025-02-05T00%3A00%3A00-08%3A00"%2C"2025-02-06T00%3A00%3A00-08%3A00"%2C"2025-02-07T00%3A00%3A00-08%3A00"%2C"2025-02-08T00%3A00%3A00-08%3A00"%2C"2025-02-09T00%3A00%3A00-08%3A00"%2C"2025-02-10T00%3A00%3A00-08%3A00"%5D%2C"type"%3A"line"%7D%5D%2C%5B"We%20are%20done!"%5D%5D%2C"state"%3A%7B"bytecodes"%3A%7B"root"%3A%7B"bytecode"%3A%5B"_H"%2C1%2C32%2C"select%20count()%2C%20event%20from%20events%20where%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20event%20order%20by%20count()%20desc%20limit%2010"%2C2%2C"run"%2C1%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C0%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C36%2C1%2C36%2C2%2C2%2C"values"%2C1%2C33%2C1%2C36%2C3%2C2%2C"length"%2C1%2C31%2C36%2C5%2C36%2C4%2C16%2C40%2C91%2C36%2C3%2C36%2C4%2C45%2C37%2C6%2C32%2C"select%20count()%2C%20toStartOfDay(timestamp)%20as%20day%20from%20events%20where%20event%20%3D%20'"%2C36%2C6%2C32%2C"'%20and%20timestamp%20>%20now()%20-%20interval%207%20day%20group%20by%20day%20order%20by%20day"%2C2%2C"concat"%2C3%2C2%2C"run"%2C1%2C36%2C6%2C32%2C"__hx_tag"%2C32%2C"Sparkline"%2C32%2C"data"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C1%2C45%2C38%2C53%2C0%2C36%2C7%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"labels"%2C52%2C"lambda"%2C1%2C0%2C6%2C36%2C0%2C33%2C2%2C45%2C38%2C53%2C0%2C36%2C7%2C32%2C"results"%2C45%2C2%2C"arrayMap"%2C2%2C32%2C"type"%2C32%2C"line"%2C42%2C4%2C2%2C"print"%2C2%2C35%2C35%2C36%2C4%2C33%2C1%2C6%2C37%2C4%2C39%2C-98%2C35%2C35%2C35%2C35%2C35%2C32%2C"We%20are%20done!"%2C2%2C"print"%2C1%5D%7D%7D%2C"stack"%3A%5B%7B"results"%3A%5B%5B11127474%2C"%24feature_flag_called"%5D%2C%5B4818997%2C"%24exception"%5D%2C%5B4704834%2C"%24autocapture"%5D%2C%5B2846874%2C"%24pageview"%5D%2C%5B2591627%2C"query%20completed"%5D%2C%5B1890908%2C"v2%20session%20recording%20snapshots%20viewed"%5D%2C%5B1594234%2C"session%20recording%20snapshots%20v2%20loaded"%5D%2C%5B1188742%2C"time%20to%20see%20data"%5D%2C%5B1185929%2C"recording%20loaded"%5D%2C%5B1140632%2C"%24groupidentify"%5D%5D%2C"columns"%3A%5B"count()"%2C"event"%5D%7D%2C%5B"%24feature_flag_called"%2C"%24exception"%2C"%24autocapture"%2C"%24pageview"%2C"query%20completed"%2C"v2%20session%20recording%20snapshots%20viewed"%2C"session%20recording%20snapshots%20v2%20loaded"%2C"time%20to%20see%20data"%2C"recording%20loaded"%2C"%24groupidentify"%5D%2Cnull%5D%2C"upvalues"%3A%5B%5D%2C"callStack"%3A%5B%5D%2C"throwStack"%3A%5B%5D%2C"declaredFunctions"%3A%7B%7D%2C"ops"%3A4745%2C"asyncSteps"%3A11%2C"syncDuration"%3A69%2C"maxMemUsed"%3A4317%7D%7D%5D&code=`

const treeData: TreeDataItem[] = [
    {
        id: 'gt_7d8f91',
        name: 'Create new',
        children: [
            {
                id: 'aichat',
                name: 'AI Chat',
                icon: <IconSparkles />,
                onClick: () => router.actions.push(urls.max()),
            },
            {
                id: 'ob2_q5r6s4t',
                name: 'Dashboard',
                icon: <IconGraph />,
                onClick: () => router.actions.push(urls.dashboards() + '#newDashboard=modal'),
            },
            {
                id: 'ssc_3d4e53',
                name: 'Experiment',
                icon: <IconTestTube />,
                onClick: () => router.actions.push(urls.experiment('new')),
            },
            {
                id: 'ssc_3d4e52',
                name: 'Feature flag',
                icon: <IconToggle />,
                onClick: () => router.actions.push(urls.featureFlag('new')),
            },
            {
                id: 'ob2_q5r6s4',
                name: 'Insight',
                children: [
                    {
                        id: 'hsc_t7u8v',
                        name: 'Trends',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.TRENDS })),
                    },
                    {
                        id: 'ob2a_w9x0y',
                        name: 'Funnels',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.FUNNELS })),
                    },
                    {
                        id: 'ob2b_z1a2b',
                        name: 'Retention',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.RETENTION })),
                    },
                    {
                        id: 'ob2b_z1a2b',
                        name: 'User Paths',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.PATHS })),
                    },
                    {
                        id: 'ob2b_z1a2b',
                        name: 'Stickiness',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.STICKINESS })),
                    },
                    {
                        id: 'ob2c_c3d4e',
                        name: 'Lifecycle',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightNew({ type: InsightType.LIFECYCLE })),
                    },
                ],
            },
            {
                id: 'ssc_3d4e5jb',
                name: 'Notebook',
                icon: <IconNotebook />,
                onClick: () => router.actions.push(urls.notebook('new')),
            },
            {
                id: 'ssc_3d4e5j',
                name: 'Repl',
                icon: <IconTarget />,
                onClick: () => router.actions.push(urls.debugHog() + '#repl=[]&code='),
            },
            {
                id: 'ssc_3d4e53r',
                name: 'Survey',
                icon: <IconMessage />,
                onClick: () => router.actions.push(urls.experiment('new')),
            },
            {
                id: 'Scene.SQLEditor',
                name: 'SQL query',
                icon: <IconServer />,
                onClick: () => router.actions.push(urls.sqlEditor()),
            },
            {
                id: 'Scene.Pipeline',
                name: 'Data pipeline',
                icon: <IconPlug />,
                children: [
                    {
                        id: 'Scene.PipelineSource',
                        name: 'Source',
                        icon: <IconPlug />,
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Source)),
                    },
                    {
                        id: 'Scene.PipelineDest',
                        name: 'Destination',
                        icon: <IconPlug />,
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Destination)),
                    },
                    {
                        id: 'Scene.PipelineTrans',
                        name: 'Transformation',
                        icon: <IconPlug />,
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.Transformation)),
                    },
                    {
                        id: 'Scene.PipelineSite',
                        name: 'Site App',
                        icon: <IconPlug />,
                        onClick: () => router.actions.push(urls.pipelineNodeNew(PipelineStage.SiteApp)),
                    },
                ],
            },
        ].sort((a, b) => a.name.localeCompare(b.name)),
    },
    {
        id: 'o_1',
        name: 'Explore data',
        icon: <IconDatabase />,
        children: [
            {
                id: 'o_1_1',
                name: 'Data management',
                icon: <IconDatabase />,
                onClick: () => router.actions.push(urls.eventDefinitions()),
            },
            {
                id: 'o_1_2',
                name: 'People and groups',
                icon: <IconPeople />,
                onClick: () => router.actions.push(urls.persons()),
            },
            {
                id: 'o_1_3',
                name: 'Activity',
                icon: <IconLive />,
                onClick: () => router.actions.push(urls.activity()),
            },
            {
                id: 'o_1_4',
                name: 'Web Analytics',
                icon: <IconPieChart />,
                onClick: () => router.actions.push(urls.webAnalytics()),
            },
            {
                id: 'o_1_5',
                name: 'Recordings',
                onClick: () => router.actions.push(urls.replay(ReplayTabs.Home)),
                icon: <IconRewindPlay />,
            },
            {
                id: 'o_1_6',
                name: 'Playlists',
                onClick: () => router.actions.push(urls.replay(ReplayTabs.Playlists)),
                icon: <IconRewindPlay />,
            },
            {
                id: 'Scene.ErrorTracking',
                name: 'Error tracking',
                icon: <IconWarning />,
                onClick: () => router.actions.push(urls.errorTracking()),
            },
            {
                id: 'Scene.Heatmaps',
                name: 'Heatmaps',
                icon: <IconCursorClick />,
                onClick: () => router.actions.push(urls.heatmaps()),
            },
        ].sort((a, b) => a.name.localeCompare(b.name)),
    },
    {
        id: 'bt_f5g6h5ee',
        name: '--------',
    },
    {
        id: 'bt_f5g6h5eexx',
        name: 'Default Project',
        icon: <IconBook />,
        onClick: () => router.actions.push(urls.projectHomepage()),
    },
    {
        id: 'gt_7d8f9j',
        name: 'Team DevEx',
        children: [
            {
                id: 'ssc_3d4e5jh',
                name: 'Hog Pivot Table',
                icon: <IconRocket />,
                onClick: () => router.actions.push(urls.debugHog() + debugHog1),
            },
            {
                id: 'ssc_3d4e5j4',
                name: 'Sparklines',
                icon: <IconTarget />,
                onClick: () => router.actions.push(urls.debugHog() + debugHog2),
            },
        ],
    },
    {
        id: 'gt_7d8f9',
        name: 'Team Growth',
        children: [
            {
                id: 'ssc_3d4e5',
                name: 'Self-serve credits',
                icon: <IconGraph />,
                disabledReason: "you're not cool enough",
            },
            {
                id: 'ot_f6g7h',
                name: 'Onboarding things',
                children: [
                    {
                        id: 'cf_8i9j0',
                        name: 'Conversion funnel',
                        icon: <IconGraph />,
                    },
                    {
                        id: 'mpu_k1l2m',
                        name: 'Multi-product usage',
                        icon: <IconGraph />,
                    },
                    {
                        id: 'pis_n3o4p',
                        name: 'Post-install survey',
                        icon: <IconGraph />,
                    },
                ],
            },
        ],
    },
]

export const treeViewLogic = kea<treeViewLogicType>([
    path(['layout', 'navigation-3000', 'components', 'treeViewLogic']),
    connect(() => ({
        values: [
            featureFlagsLogic,
            ['featureFlags'],
            savedInsightsLogic,
            ['insights'],
            experimentsLogic,
            ['experiments'],
            dashboardsLogic,
            ['dashboards'],
            notebooksTableLogic,
            ['notebooks'],
        ],
        actions: [notebooksTableLogic, ['loadNotebooks']],
    })),
    actions({ setTreeData: (treeData: TreeDataItem[]) => ({ treeData }) }),
    reducers({ treeData: [treeData, { setTreeData: (_, { treeData }) => treeData }] }),
    selectors({
        unfilled: [
            (s) => [s.featureFlags, s.insights, s.experiments, s.dashboards, s.notebooks],
            (featureFlags, insights, experiments, dashboards, notebooks): TreeDataItem[] => {
                return [
                    ...featureFlags.results.map((f) => ({
                        id: `ff_${f.id}`,
                        name: f.name || 'Untitled',
                        icon: <IconToggle />,
                        onClick: () => router.actions.push(urls.featureFlag(Number(f.id))),
                    })),
                    ...insights.results.map((i) => ({
                        id: `insight_${i.id}`,
                        name: i.name || 'Untitled',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.insightView(i.short_id)),
                    })),
                    ...experiments.map((e) => ({
                        id: `exp_${e.id}`,
                        name: e.name || 'Untitled',
                        icon: <IconTestTube />,
                        onClick: () => router.actions.push(urls.experiment(e.id)),
                    })),
                    ...dashboards.map((d) => ({
                        id: `dash_${d.id}`,
                        name: d.name || 'Untitled',
                        icon: <IconGraph />,
                        onClick: () => router.actions.push(urls.dashboard(d.id)),
                    })),
                    ...notebooks.map((n) => ({
                        id: `nb_${n.id}`,
                        name: n.title || 'Untitled',
                        icon: <IconNotebook />,
                        onClick: () => router.actions.push(urls.notebook(n.short_id)),
                    })),
                ].sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
    }),
    subscriptions(({ actions }) => ({
        unfilled: (unfilled) => {
            actions.setTreeData([
                ...treeData,
                {
                    id: 'uf_u5v6w',
                    name: 'Unfilled',
                    children: unfilled,
                },
            ])
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNotebooks()
    }),
])
