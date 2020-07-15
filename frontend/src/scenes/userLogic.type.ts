// Auto-generated with kea-typegen v0.0.10. DO NOT EDIT!

export interface userLogicType<UserType> {
    actionCreators: {
        loadUser: () => ({
            type: "load user (frontend.src.scenes.userLogic)";
            payload: {
                value: boolean;
            };
        });
        setUser: (user: UserType | null, updateKey?: string) => ({
            type: "set user (frontend.src.scenes.userLogic)";
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({
            type: "user update request (frontend.src.scenes.userLogic)";
            payload: { update: Partial<UserType>; updateKey: string | undefined; };
        });
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({
            type: "user update success (frontend.src.scenes.userLogic)";
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateFailure: (error: string, updateKey?: string) => ({
            type: "user update failure (frontend.src.scenes.userLogic)";
            payload: { updateKey: string | undefined; error: string; };
        });
    };
    actions: {
        loadUser: () => ({
            type: "load user (frontend.src.scenes.userLogic)";
            payload: {
                value: boolean;
            };
        });
        setUser: (user: UserType | null, updateKey?: string) => ({
            type: "set user (frontend.src.scenes.userLogic)";
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => ({
            type: "user update request (frontend.src.scenes.userLogic)";
            payload: { update: Partial<UserType>; updateKey: string | undefined; };
        });
        userUpdateSuccess: (user: UserType, updateKey?: string) => ({
            type: "user update success (frontend.src.scenes.userLogic)";
            payload: { user: UserType; updateKey: string | undefined; };
        });
        userUpdateFailure: (error: string, updateKey?: string) => ({
            type: "user update failure (frontend.src.scenes.userLogic)";
            payload: { updateKey: string | undefined; error: string; };
        });
    };
    reducer: (state: any, action: () => any, fullState: any) => {
        user: UserType | null;
    };
    reducers: {
        user: (state: UserType | null, action: any, fullState: any) => UserType | null;
    };
    selector: (state: any) => {
        user: UserType | null;
    };
    selectors: {
        user: (state: any, props: any) => UserType | null;
        eventProperties: (state: any, props: any) => { value: string; label: string; }[];
        eventNames: (state: any, props: any) => string[] | undefined;
        customEventNames: (state: any, props: any) => string[];
        eventNamesGrouped: (state: any, props: any) => { label: string; options: { label: string; value: string; }[]; }[];
    };
    values: {
        user: UserType | null;
        eventProperties: { value: string; label: string; }[];
        eventNames: string[] | undefined;
        customEventNames: string[];
        eventNamesGrouped: { label: string; options: { label: string; value: string; }[]; }[];
    };
    __selectorTypeHelp: {
        eventProperties: (arg0: UserType | null) => { value: string; label: string; }[];
        eventNames: (arg0: UserType | null) => string[] | undefined;
        customEventNames: (arg0: UserType | null) => string[];
        eventNamesGrouped: (arg0: UserType | null) => { label: string; options: { label: string; value: string; }[]; }[];
    };
}