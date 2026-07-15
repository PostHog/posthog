import { kea, key, path, props, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { codeSceneLogicType } from './codeSceneLogicType'

/** Sections of the PostHog Code demo surface (products/desktop). 'home' is the default. */
export type CodeSceneSection = 'home' | 'agents' | 'skills' | 'mcp-servers' | 'command-center' | 'contexts'

export const CODE_SECTION_LABELS: Record<CodeSceneSection, string> = {
    home: 'Home',
    agents: 'Agents',
    skills: 'Skills',
    'mcp-servers': 'MCP servers',
    'command-center': 'Command Center',
    contexts: 'Contexts',
}

export interface CodeSceneLogicProps {
    section: CodeSceneSection
}

export const codeSceneLogic = kea<codeSceneLogicType>([
    path((key) => ['scenes', 'code', 'codeSceneLogic', key]),
    props({} as CodeSceneLogicProps),
    key(({ section }) => section),
    selectors({
        section: [(_, p) => [p.section], (section: CodeSceneSection): CodeSceneSection => section],
        breadcrumbs: [
            (_, p) => [p.section],
            (section: CodeSceneSection): Breadcrumb[] => [
                { key: Scene.Code, name: 'Code', path: urls.code(), iconType: 'task' },
                { key: [Scene.Code, section], name: CODE_SECTION_LABELS[section], iconType: 'task' },
            ],
        ],
    }),
])
