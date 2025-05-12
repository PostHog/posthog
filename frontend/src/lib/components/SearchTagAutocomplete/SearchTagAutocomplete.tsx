import { IconSearch, IconX } from "@posthog/icons";
import { LemonInput } from "lib/lemon-ui/LemonInput";
import { ButtonPrimitive } from "lib/ui/Button/ButtonPrimitives";
import { ListBox, ListBoxHandle } from "lib/ui/ListBox/ListBox";
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from "lib/ui/PopoverPrimitive/PopoverPrimitive";
import { forwardRef, useState, useRef, useEffect } from "react";

type Category = string;
type Suggestion = { label: string; value: string };
type Hint = string;

export interface SearchWithTagsProps {
    inputPlaceholder?: string;
    defaultSearchTerm?: string;
    onChange?: (value: string) => void;
    onClear?: () => void;
    onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
    className?: string;
    defaultOpen?: boolean;
    alwaysOpen?: boolean;
    onSelect?: (value: string) => void;
    searchData: [Category, Suggestion[] | undefined, Hint?][];
    autoFocus?: boolean;
}

export const SearchTagAutocomplete = forwardRef<HTMLInputElement, SearchWithTagsProps>(
    (
        {
            inputPlaceholder,
            onChange,
            onSelect,
            searchData,
            autoFocus,
            onClear,
        },
        _,
    ): JSX.Element => {
        const [value, setValue] = useState('');
        const [open, setOpen] = useState(false);
        const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
        const [currentHint, setCurrentHint] = useState<string | undefined>(undefined);
        const inputRef = useRef<HTMLInputElement>(null);
        const listBoxRef = useRef<ListBoxHandle>(null);

        const baseCategories = searchData.map(([cat]) => ({ value: cat, label: cat }));

        const getLastToken = (input: string) => {
            const tokens = input.trim().split(/\s+/);
            return tokens[tokens.length - 1];
        };

        const getSuggestions = (input: string) => {
            const lastToken = getLastToken(input);
            const [category, partialRaw = ""] = lastToken.split(":");
            
            const matched = searchData.find(([cat]) => cat === category);
            
            const partial = partialRaw;
            const cleanPartial =
            partial.startsWith("!") || partial.startsWith("-")
            ? partial.slice(1)
            : partial;

            if (matched) {
                if (!lastToken.endsWith(':')) {
                    setCurrentHint('choose an option or enter a colon ":" then a value');                            
                } else {
                    setCurrentHint(matched[2]);                    
                }
            } else {
                setCurrentHint(undefined);
            }

            if (lastToken.endsWith(":") && matched) {
                return matched[1] || [];
            }

            if (
                matched &&
                matched[1] &&
                matched[1].some((s) => s.value.toLowerCase() === cleanPartial.toLowerCase())
            ) {
                setCurrentHint(undefined);
                return [];
            }

            if (
                matched &&
                matched[1] &&
                (cleanPartial === "" || partial.startsWith("!") || partial.startsWith("-"))
            ) {
                return matched[1];
            }

            if (matched && matched[1] && cleanPartial !== "") {
                return matched[1].filter((s) =>
                    s.label.toLowerCase().startsWith(cleanPartial.toLowerCase())
                );
            }

            if (!lastToken.includes(":")) {
                return baseCategories.filter((cat) =>
                    cat.label.toLowerCase().startsWith(lastToken.toLowerCase())
                );
            }

            return [];
        };

        const handleChange = (val: string) => {
            setValue(val);
            if (val.length === 0) {
                setOpen(false);
                setSuggestions(baseCategories);
                setCurrentHint(undefined);
                return;
            }

            
            const inputEndsWithSpace = val.endsWith(" ");
            
            if (inputEndsWithSpace) {
                setSuggestions(baseCategories)
                setOpen(true);
            } else {
                const newSuggestions = getSuggestions(val);
                setSuggestions(newSuggestions);
                setOpen(newSuggestions.length > 0 || !!currentHint);
            }

            console.log('on change', val)
            onChange?.(val);
        };

        const handleSuggestionClick = (suggestion: Suggestion) => {
            const tokens = value.trim().split(/\s+/);
            const lastToken = getLastToken(value);
            const [category, partialRaw = ""] = lastToken.split(":");
            const matched = searchData.find(([cat]) => cat === category);

            const isCategory = searchData.some(([cat]) => cat === suggestion.value);
            const inputEndsWithSpace = value.endsWith(" ");

            let newInput = "";

            if (isCategory) {
                if (inputEndsWithSpace || value === "") {
                    tokens.push(`${suggestion.value}:`);
                } else {
                    tokens[tokens.length - 1] = `${suggestion.value}:`;
                }
                newInput = tokens.join(" ").trim();
                setSuggestions(getSuggestions(newInput));
            } else if (matched && matched[1]) {
                const negationPrefix =
                    partialRaw.startsWith("!") || partialRaw.startsWith("-")
                        ? partialRaw[0]
                        : "";
                tokens[tokens.length - 1] = `${category}:${negationPrefix}${suggestion.value}`;
                newInput = tokens.join(" ").trim() + " ";
                setSuggestions(baseCategories);
                setCurrentHint(undefined);
            }

            setValue(newInput);
            setOpen(true);

            onSelect?.(suggestion.value);

            focusInput();
        };

        const handleKeydown = (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (!open || suggestions.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                listBoxRef.current?.focusFirstElement();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                listBoxRef.current?.focusNthElement(suggestions.length - 1);
            } else if (e.key === 'Enter') {
                setOpen(false);
            }
        };

        // const handleFocus = () => {
        //     // if input empty, show dropdown with base categories
        //     if (value.length === 0) {
        //         setSuggestions(baseCategories);
        //         setOpen(true);
        //     }
        // }

        const focusInput = () => {
            const input = inputRef.current;
            if (input) {
                input.focus();
                // set the cursor to the end of the input
                const length = input.value.length;
                input.setSelectionRange(length, length);
            }
        }

        useEffect(() => {
            setSuggestions(baseCategories);
        }, [searchData]);

        return (
            <PopoverPrimitive open={open} onOpenChange={setOpen}>
                <PopoverPrimitiveTrigger asChild>
                    <LemonInput
                        type="text"
                        placeholder={inputPlaceholder}
                        className="w-full"
                        onChange={(val) => handleChange(val)}
                        value={value}
                        onKeyDown={handleKeydown}
                        // onFocus={handleFocus}
                        aria-label="Search input"
                        inputRef={inputRef}
                        aria-expanded={open}
                        aria-controls="suggestions-list"
                        aria-autocomplete="list"
                        size="small"
                        prefix={
                            <div className="flex items-center justify-center size-4 ml-[2px] mr-px">
                                <IconSearch className="size-4" />
                            </div>
                        }
                        suffix={
                            value && onClear ? (
                                <ButtonPrimitive
                                    size="sm"
                                    iconOnly
                                    onClick={() => onClear()}
                                    className="bg-transparent [&_svg]:opacity-50 hover:[&_svg]:opacity-100 focus-visible:[&_svg]:opacity-100 -mr-px"
                                    tooltip="Clear search"
                                >
                                    <IconX className="size-4" />
                                </ButtonPrimitive>
                            ) : null
                        }
                        autoFocus={autoFocus}
                    />
                </PopoverPrimitiveTrigger>
                {/* {open && (suggestions.length > 0 || currentHint) && ( */}
                {open && (
                    <PopoverPrimitiveContent
                        onCloseAutoFocus={(e) => {
                            e.preventDefault();
                            requestAnimationFrame(() => {
                                focusInput();
                            });
                        }}
                        onOpenAutoFocus={(e) => e.preventDefault()}
                        className="primitive-menu-content w-[var(--radix-popover-trigger-width)] max-w-none"
                    >
                        <ListBox ref={listBoxRef} className="flex flex-col gap-px p-1">
                            {suggestions.map((item) => (
                                <ListBox.Item asChild key={item.value}>
                                    <ButtonPrimitive
                                        onClick={() => handleSuggestionClick(item)}
                                        menuItem
                                    >
                                        {item.label}
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            ))}
                            {currentHint && (
                                <div className="px-2 py-1 text-sm text-muted">
                                    {currentHint}
                                </div>
                            )}
                        </ListBox>
                    </PopoverPrimitiveContent>
                )}
            </PopoverPrimitive>
        );
    }
);
