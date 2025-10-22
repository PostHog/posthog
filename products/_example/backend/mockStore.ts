import { ExampleAppMockPerson } from '../frontend/ExampleAppScene'

let mockPersonsData: ExampleAppMockPerson[] = [
    {
        id: '1',
        name: 'Alice Johnson',
        description: 'Senior Software Engineer specializing in full-stack development',
        createdAt: '2025-09-15',
        updatedAt: '2025-10-20',
    },
    {
        id: '2',
        name: 'Bob Smith',
        description: 'Product Manager with expertise in user experience design',
        createdAt: '2025-09-22',
        updatedAt: '2025-10-18',
    },
    {
        id: '3',
        name: 'Carol Davis',
        description: 'Data Scientist focused on machine learning and analytics',
        createdAt: '2025-10-01',
        updatedAt: '2025-10-21',
    },
    {
        id: '4',
        name: 'David Wilson',
        description: 'DevOps Engineer managing cloud infrastructure',
        createdAt: '2025-10-05',
        updatedAt: '2025-10-19',
    },
    {
        id: '5',
        name: 'Eva Chen',
        description: 'UX Designer creating intuitive user interfaces',
        createdAt: '2025-10-10',
        updatedAt: '2025-10-22',
    },
    {
        id: '6',
        name: 'Frank Miller',
        description: 'Security Engineer ensuring application safety',
        createdAt: '2025-10-12',
        updatedAt: '2025-10-21',
    },
]

export async function fetchMockPersons(): Promise<ExampleAppMockPerson[]> {
    await new Promise((resolve) => setTimeout(resolve, 1000))

    return [...mockPersonsData]
}

export async function fetchMockPerson(id: string): Promise<ExampleAppMockPerson | null> {
    await new Promise((resolve) => setTimeout(resolve, 800))
    const person = mockPersonsData.find((p) => p.id === id)
    return person ? { ...person } : null
}

export async function createMockPerson(
    person: Omit<ExampleAppMockPerson, 'id' | 'createdAt' | 'updatedAt'>
): Promise<ExampleAppMockPerson> {
    await new Promise((resolve) => setTimeout(resolve, 1200))

    const newPerson: ExampleAppMockPerson = {
        ...person,
        id: (mockPersonsData.length + 1).toString(),
        createdAt: new Date().toISOString().split('T')[0],
        updatedAt: new Date().toISOString().split('T')[0],
    }

    mockPersonsData.push(newPerson)
    return { ...newPerson }
}

export async function updateMockPerson(
    id: string,
    updates: Partial<Pick<ExampleAppMockPerson, 'name' | 'description'>>
): Promise<ExampleAppMockPerson> {
    await new Promise((resolve) => setTimeout(resolve, 1000))

    const personIndex = mockPersonsData.findIndex((p) => p.id === id)
    if (personIndex === -1) {
        throw new Error(`Person with id ${id} not found`)
    }

    mockPersonsData[personIndex] = {
        ...mockPersonsData[personIndex],
        ...updates,
        updatedAt: new Date().toISOString().split('T')[0],
    }

    return { ...mockPersonsData[personIndex] }
}

export async function deleteMockPerson(id: string): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 800))

    const personIndex = mockPersonsData.findIndex((p) => p.id === id)
    if (personIndex === -1) {
        throw new Error(`Person with id ${id} not found`)
    }

    mockPersonsData.splice(personIndex, 1)
}
