import { kea, resetContext, keaReducer } from '../../src'

describe('logic singleton', () => {
  beforeEach(() => {
    resetContext()
  })

  test('singleton logic has all the right properties', () => {
    keaReducer('scenes')

    const response = kea({
      path: () => ['scenes', 'homepage', 'index'],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions }) => ({
        name: [
          'chirpy',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        upperCaseName: [
          () => [selectors.capitalizedName],
          (capitalizedName) => {
            return capitalizedName.toUpperCase()
          },
        ],
        capitalizedName: [
          () => [selectors.name],
          (name) => {
            return name
              .trim()
              .split(' ')
              .map((k) => `${k.charAt(0).toUpperCase()}${k.slice(1).toLowerCase()}`)
              .join(' ')
          },
        ],
      }),
    })

    expect(response._isKea).toBe(true)

    expect(() => {
      response.path
    }).toThrow() // eslint-disable-line
    expect(() => {
      response.actions
    }).toThrow() // eslint-disable-line
    expect(() => {
      response.selectors
    }).toThrow() // eslint-disable-line

    response.mount()

    // check generic
    expect(response.path).toEqual(['scenes', 'homepage', 'index'])
    expect(Object.keys(response.connections)).toEqual(['scenes.homepage.index'])

    // actions
    expect(Object.keys(response.actions)).toEqual(['updateName'])
    const { updateName } = response.actionCreators
    expect(typeof updateName).toBe('function')
    expect(updateName.toString()).toBe('update name (scenes.homepage.index)')
    expect(updateName('newname')).toEqual({ payload: { name: 'newname' }, type: updateName.toString() })

    // reducers
    const defaultValues = { name: 'chirpy' }
    const state = { scenes: { homepage: { index: defaultValues } } }
    expect(Object.keys(response.reducers).sort()).toEqual(['name'])

    expect(response.reducers).toHaveProperty('name')
    expect(response.defaults.name).toEqual('chirpy')

    const nameReducer = response.reducers.name
    expect(nameReducer).toBeDefined()
    expect(nameReducer('', updateName('newName'))).toBe('newName')

    expect(response.reducers).not.toHaveProperty('capitalizedName')
    expect(response.defaults).not.toHaveProperty('capitalizedName', 'chirpy')

    // big reducer
    expect(typeof response.reducer).toBe('function')
    expect(response.reducer({}, { type: 'random action' })).toEqual(defaultValues)
    expect(response.reducer({ name: 'something' }, { type: 'random action' })).toEqual({ name: 'something' })
    expect(response.reducer({ name: 'something' }, updateName('newName'))).toEqual({ name: 'newName' })

    // selectors
    expect(Object.keys(response.selectors).sort()).toEqual(['capitalizedName', 'name', 'upperCaseName'])
    expect(response.selectors.name(state)).toEqual('chirpy')
    expect(response.selectors.capitalizedName(state)).toEqual('Chirpy')
    expect(response.selectors.upperCaseName(state)).toEqual('CHIRPY')

    // root selector
    expect(response.selector(state)).toEqual(defaultValues)
  })

  test('it is not a singleton if there is a key', () => {
    keaReducer('scenes')

    const response = kea({
      key: (props) => props.id,
      path: (key) => ['scenes', 'homepage', 'index', key],
      actions: () => ({
        updateName: (name) => ({ name }),
      }),
      reducers: ({ actions }) => ({
        name: [
          'chirpy',
          {
            [actions.updateName]: (state, payload) => payload.name,
          },
        ],
      }),
      selectors: ({ selectors }) => ({
        capitalizedName: [
          () => [selectors.name],
          (name) => {
            return name
              .trim()
              .split(' ')
              .map((k) => `${k.charAt(0).toUpperCase()}${k.slice(1).toLowerCase()}`)
              .join(' ')
          },
        ],
      }),
    })

    expect(() => response.mount()).toThrow()

    // check generic
    expect(response._isKea).toBe(true)

    expect(() => response.path).toThrow()

    // actions
    expect(() => response.actions).toThrow()

    // reducers
    expect(() => response.reducer).toThrow()
    expect(() => response.reducers).toThrow()

    // selectors
    expect(() => response.selector).toThrow()
    expect(() => response.selectors).toThrow()
  })
})
