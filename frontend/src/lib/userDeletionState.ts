// Module-level flag used to suppress loader error toasts during the brief window
// between a successful account deletion and the form-POST logout navigation.
// Lives outside any kea logic so initKea can check it without importing userLogic
// (which would pull a large dependency graph into the bootstrap module).

let userIsBeingDeleted = false

export function setUserIsBeingDeleted(value: boolean): void {
    userIsBeingDeleted = value
}

export function getUserIsBeingDeleted(): boolean {
    return userIsBeingDeleted
}
