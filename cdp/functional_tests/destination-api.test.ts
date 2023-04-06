/*

Tests for a basic CRUD API for destinations supporting GET, POST, PUT, and
DELETE, corresponding to creating, reading, updating, and deleting destinations
as well as other similar operations.

We also have an API for the list of destination types, which provides a list of
types along with the schema for the configuration for each type. This is used
to validate the configuration for each destination.

We do not attempt to handle e.g. idempotency of requests although that may be a
good idea if we hit issues with e.g. retry logic and concurrency. See for
example https://www.mscharhag.com/api-design/rest-making-post-patch-idempotent
for an example way to implement this.

*/

import { describe, test, expect } from '@jest/globals'

describe('DestinationType API', () => {
    describe('GET destination types', () => {
        test.concurrent('should be able to retrieve a list of destination types', async () => {
            const destinationTypes = await listDestinationTypesOk()
            expect(destinationTypes).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        type: 'webhook',
                        configSchema: expect.any(Object),
                    }),
                ])
            )
        })
    })
})

describe('Destination API', () => {
    describe('POST destination', () => {
        test.concurrent('should be able to create a destination', async () => {
            const projectId = (await createProjectOk()).id
            const response = await postDestination(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: {
                    url: 'https://example.com',
                },
            })
            expect(response.status).toEqual(201)
        })

        test.concurrent('should not be able to create a destination with an invalid config schema', async () => {
            const projectId = (await createProjectOk()).id
            const response = await postDestination(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: {
                    invalid: 'config',
                },
            })
            expect(response.status).toEqual(400)
        })
    })

    describe('GET destination', () => {
        test.concurrent('should be able to retrieve a destination', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            const retrievedDestination = await getDestinationOk(projectId, destinationId)
            expect(retrievedDestination).toEqual(expect.objectContaining(destination))
        })

        test.concurrent('should not be able to retrieve a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const otherProjectId = (await createProjectOk()).id
            const response = await getDestination(otherProjectId, destinationId)
            expect(response.status).toEqual(404)
        })
    })

    describe('PUT destination', () => {
        test.concurrent('should be able to update a destination', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const updatedDestination = await putDestinationOk(projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(updatedDestination).toEqual(
                expect.objectContaining({
                    id: destinationId,
                    name: 'Updated Destination',
                    description: 'Updated Description',
                })
            )
        })

        test.concurrent('should not be able to update a destination with an invalid config schema', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const response = await putDestination(projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { invalid: 'config' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to change the destination type', async () => {
            // For simplicity of handling e.g. the schema of `config` do not
            // want to allow changing the destination type rather the user
            // should delete and recreate a distination.
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()
            const response = await putDestination(projectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'email',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to update a destination with an invalid id', async () => {
            const projectId = (await createProjectOk()).id
            const response = await putDestination(projectId, 'invalid', {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to update a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const otherProjectId = (await createProjectOk()).id
            const response = await putDestination(otherProjectId, destinationId, {
                name: 'Updated Destination',
                description: 'Updated Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            expect(response.status).toEqual(404)
        })
    })

    describe('DELETE destination', () => {
        test.concurrent('should be able to delete a destination', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const response = await deleteDestination(projectId, destinationId)
            expect(response.status).toEqual(204)

            // Check that the destination is no longer retrievable
            const getResponse = await getDestination(projectId, destinationId)
            expect(getResponse.status).toEqual(404)
        })

        test.concurrent('should not be able to delete a destination with an invalid id', async () => {
            const id = 'invalid'
            const projectId = (await createProjectOk()).id
            const response = await deleteDestination(projectId, id)
            expect(response.status).toEqual(400)
        })

        test.concurrent('should not be able to delete a destination from another project', async () => {
            const projectId = (await createProjectOk()).id
            const destination = await postDestinationOk(projectId, {
                name: 'Test Destination',
                description: 'Test Description',
                type: 'webhook',
                config: { url: 'https://example.com' },
            })
            const destinationId = destination.id
            expect(destinationId).toBeDefined()

            const otherProjectId = (await createProjectOk()).id
            const response = await deleteDestination(otherProjectId, destinationId)
            expect(response.status).toEqual(404)

            // Check that the destination is still retrievable
            const getResponse = await getDestination(projectId, destinationId)
            expect(getResponse.status).toEqual(200)
        })
    })
})

const listDestinationTypes = async (projectId: number): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destination-types`)
}

const listDestinationTypesOk = async (): Promise<DestinationType[]> => {
    const projectId = (await createProjectOk()).id
    const response = await listDestinationTypes(projectId)
    if (!response.ok) {
        throw new Error(`Failed to list destination types: ${response.statusText}`)
    }
    return await response.json()
}

const postDestination = async (projectId: number, destinationData: DestinationCreate): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(destinationData),
    })
}

const postDestinationOk = async (projectId: number, destinationData: DestinationCreate): Promise<Destination> => {
    const response = await postDestination(projectId, destinationData)
    if (!response.ok) {
        throw new Error(`Failed to create destination: ${response.statusText}`)
    }
    return await response.json()
}

const putDestination = async (projectId: number, id: string, destinationData: DestinationUpdate): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(destinationData),
    })
}

const putDestinationOk = async (
    projectId: number,
    id: string,
    destinationData: DestinationUpdate
): Promise<Destination> => {
    const response = await putDestination(projectId, id, destinationData)
    if (!response.ok) {
        throw new Error(`Failed to update destination: ${response.statusText}`)
    }
    return await response.json()
}

const getDestination = async (projectId: number, id: string): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`)
}

const getDestinationOk = async (projectId: number, id: string): Promise<Destination> => {
    const response = await getDestination(projectId, id)
    if (!response.ok) {
        throw new Error(`Failed to retrieve destination: ${response.statusText}`)
    }
    return await response.json()
}

const deleteDestination = async (projectId: number, id: string): Promise<Response> => {
    return await fetch(`http://localhost:3000/api/projects/${projectId}/destinations/${id}`, {
        method: 'DELETE',
    })
}

const createProjectOk = async (): Promise<{ id: number }> => {
    // This isn't really an API method but rather a helper method to create a
    // projectId.
    return { id: Math.floor(Math.random() * 100000) }
}

type DestinationType = {
    type: string
    name: string
    description: string
    schema: Record<string, unknown> // A JSONSchema describing the configuration
}

type DestinationCreate = {
    name: string // Name displayed to the user
    description: string // Description displayed to the user
    type: string // Type of destination, e.g. webhook, email, Stripe etc.
    config: Record<string, unknown> // Configuration for the destination, e.g. webhook URL, email address, Stripe API key etc.
}

type DestinationUpdate = DestinationCreate

type Destination = DestinationCreate & {
    id: string
    created_at: string // ISO 8601 timestamp
    updated_at: string // ISO 8601 timestamp
}
