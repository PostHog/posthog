import { sceneConfigurations } from 'scenes/scenes'

import { fileSystemTypes } from '~/products'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemType } from '~/types'

import { EntityListDefinition } from './types'

/**
 * Every entity list registered so far, keyed by its file system type.
 *
 * Scene modules are code-split, so a definition only lands here once its scene has been loaded.
 * That is enough for the scene itself and for anything reached from a mounted list; a surface that
 * needs to enumerate every list up front would have to register from the product manifests instead.
 */
const REGISTRY = new Map<string, EntityListDefinition<any>>()

export function registerEntityList<T extends Record<string, any>>(
    definition: EntityListDefinition<T>
): EntityListDefinition<T> {
    REGISTRY.set(definition.type, definition)
    return definition
}

export function getEntityList(type: string): EntityListDefinition<any> | undefined {
    return REGISTRY.get(type)
}

export function getRegisteredEntityLists(): EntityListDefinition<any>[] {
    return [...REGISTRY.values()]
}

/** Definition fields merged with what the product manifest and the scene config already declare. */
export interface ResolvedEntityListMeta {
    name: string
    description?: string
    iconType: FileSystemIconType
    nouns: [string, string]
    /** Detail page builder from the file system registry, when the type is registered there. */
    detailUrl?: (ref: string) => string
}

export function resolveEntityListMeta(definition: EntityListDefinition<any>): ResolvedEntityListMeta {
    // Only the fields an entity list needs: `fileSystemTypes` as a whole isn't uniformly typed.
    const registered = fileSystemTypes as Record<string, Pick<FileSystemType, 'name' | 'iconType' | 'href'>>
    const fileSystemType = registered[definition.type]
    const sceneConfig = sceneConfigurations[definition.scene]
    const name = definition.name ?? sceneConfig?.name ?? fileSystemType?.name ?? definition.type
    const singular = fileSystemType?.name?.toLowerCase() ?? name.toLowerCase()

    return {
        name,
        description: definition.description ?? sceneConfig?.description,
        iconType: definition.iconType ?? fileSystemType?.iconType ?? sceneConfig?.iconType ?? 'default_icon_type',
        nouns: definition.nouns ?? [singular, `${singular}s`],
        detailUrl: fileSystemType?.href,
    }
}
