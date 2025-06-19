import { IconCheck, IconCopy, IconDocument, IconFolderOpen, IconGear, IconGraph, IconPlusSmall, IconShare } from "@posthog/icons";
import { IconBlank, IconChevronRight } from "lib/lemon-ui/icons";
import { Link } from "lib/lemon-ui/Link";
import { ButtonPrimitive, buttonPrimitiveVariants } from "lib/ui/Button/ButtonPrimitives";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from "scenes/urls";
import { breadcrumbsLogic } from "../navigation/Breadcrumbs/breadcrumbsLogic";
import { useActions, useValues } from "kea";
import { cn } from "lib/utils/css-classes";
import { sidePanelSettingsLogic } from "../navigation-3000/sidepanel/panels/sidePanelSettingsLogic";
import { topBarSettingsButtonLogic } from "lib/components/TopBarSettingsButton/topBarSettingsButtonLogic";

export function SceneHeader(): JSX.Element {
    const { setActionsContainer } = useActions(breadcrumbsLogic)
    const { loadedSceneSettingsSectionId } = useValues(topBarSettingsButtonLogic)
    const { openSettingsPanel, closeSettingsPanel } = useActions(sidePanelSettingsLogic)
    const { isOpen: isSettingsPanelOpen } = useValues(sidePanelSettingsLogic)

    return <header>
        <div className="flex justify-center h-[68px] border-b border-primary px-2">
            <div className="flex gap-[6px] flex-1 items-center">
                <Link to={urls.activity()} buttonProps={{
                    size: 'base',
                    className: 'size-[52px] bg-[#2F80FA] hover:bg-[#498df4] rounded flex justify-center items-center'
                }}>

                    <IconGraph className="fill-white size-[30px]" />
                </Link>
                <div className="flex flex-col gap-px">
                    <h1 className={cn(buttonPrimitiveVariants(), 'text-[18px] font-semibold m-0')}>
                        Go/Revenue
                    </h1>
                    <ul className="list">
                        <li>
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <ButtonPrimitive>
                                        File
                                    </ButtonPrimitive>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent loop align="start" side="bottom" className="max-w-[250px]">
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconPlusSmall /> New 
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconCopy /> Make a copy
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconFolderOpen /> Open in file tree
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>

                                    <DropdownMenuSub>
                                        <DropdownMenuSubTrigger asChild>
                                            <ButtonPrimitive menuItem>
                                                <IconShare /> Export <IconChevronRight className="ml-auto" />
                                            </ButtonPrimitive>
                                        </DropdownMenuSubTrigger>
                                        <DropdownMenuSubContent>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .png
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .csv
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .xlsx
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>

                                        </DropdownMenuSubContent>
                                    </DropdownMenuSub>

                                </DropdownMenuContent>
                            </DropdownMenu>
                            
                            
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <ButtonPrimitive>
                                        Edit
                                    </ButtonPrimitive>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent loop align="start" side="bottom" className="max-w-[250px]">
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconPlusSmall /> New
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconCopy /> Make a copy
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconFolderOpen /> Open in file tree
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>

                                    <DropdownMenuSub>
                                        <DropdownMenuSubTrigger asChild>
                                            <ButtonPrimitive menuItem>
                                                <IconShare /> Export <IconChevronRight className="ml-auto" />
                                            </ButtonPrimitive>
                                        </DropdownMenuSubTrigger>
                                        <DropdownMenuSubContent>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .png
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .csv
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>
                                            <DropdownMenuItem asChild>
                                                <ButtonPrimitive menuItem>
                                                    <IconDocument /> .xlsx
                                                </ButtonPrimitive>
                                            </DropdownMenuItem>

                                        </DropdownMenuSubContent>
                                    </DropdownMenuSub>

                                </DropdownMenuContent>
                            </DropdownMenu>
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <ButtonPrimitive>
                                        View
                                    </ButtonPrimitive>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent loop align="start" side="bottom" className="max-w-[250px]">
                                    {loadedSceneSettingsSectionId ? (
                                        <DropdownMenuItem
                                            asChild
                                        >
                                            <ButtonPrimitive menuItem onClick={() =>
                                                isSettingsPanelOpen ? closeSettingsPanel() : openSettingsPanel({ sectionId: loadedSceneSettingsSectionId })
                                            }>
                                                {isSettingsPanelOpen ? <IconCheck/> : <IconBlank/>} <IconGear /> Settings
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                    ): null}
                                </DropdownMenuContent>
                            </DropdownMenu>
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <ButtonPrimitive>
                                        Help
                                    </ButtonPrimitive>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent loop align="start" side="bottom" className="max-w-[250px]">
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconPlusSmall /> New
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconCopy /> Make a copy
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                    >
                                        <ButtonPrimitive menuItem>
                                            <IconFolderOpen /> Open in file tree
                                        </ButtonPrimitive>
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        </li>
                    </ul>
                </div>
            </div>
            <div ref={setActionsContainer} className="h-full flex items-center"/>
        </div>
    </header>
}