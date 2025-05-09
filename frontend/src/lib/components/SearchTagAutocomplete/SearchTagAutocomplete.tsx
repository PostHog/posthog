import { IconSearch } from "@posthog/icons";
import { LemonInput } from "lib/lemon-ui/LemonInput";
import { ButtonPrimitive } from "lib/ui/Button/ButtonPrimitives";
import { ListBox, ListBoxHandle } from "lib/ui/ListBox/ListBox";
import { PopoverPrimitive, PopoverPrimitiveContent, PopoverPrimitiveTrigger } from "lib/ui/PopoverPrimitive/PopoverPrimitive";
import { forwardRef, useState, useRef } from "react";

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
    onSubmit?: (value: string) => void;
}

export const SearchTagAutocomplete = forwardRef<HTMLInputElement, SearchWithTagsProps>(
    (): JSX.Element => {
        const data = [
            'abe lincoln',
            'dennis ritchie',
            'alan kay',
            'larry page',
            'sergey brin',
            'tim berners-lee',
            'linus torvalds',
        ]
        const [value, setValue] = useState('');
        const [open, setOpen] = useState(true);
        const [suggestions, setSuggestions] = useState<string[]>(data);
        const inputRef = useRef<HTMLInputElement>(null);
        const listBoxRef = useRef<ListBoxHandle>(null);

        const handleChange = (value: string) => {
            setValue(value);
            if (value.length > 0) {
                setOpen(true);
            } else {
                setOpen(false);
            }
    
            setSuggestions(data.filter(item => item.toLowerCase().includes(value.toLowerCase())));
        }
    
        const handleSuggestionClick = (suggestion: string) => {
            setValue(suggestion);
            setOpen(false);
            inputRef.current?.focus();
        }
    
        const handleKeydown = (e: React.KeyboardEvent<HTMLInputElement>) => {
            if (!open || suggestions.length === 0) return;
    
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (suggestions.length > 0 && open) {
                    listBoxRef.current?.focusFirstElement()
                }
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (suggestions.length > 0 && open) {
                    // Focus the last button in the suggestions list
                    listBoxRef.current?.focusNthElement(suggestions.length - 1)
                }
            }
        }
 
        return (
                <PopoverPrimitive open={open} onOpenChange={setOpen}>
                    <PopoverPrimitiveTrigger asChild>
                        <LemonInput 
                            type="text" 
                            className='w-full' 
                            onChange={(value) => handleChange(value)} 
                            value={value} 
                            onKeyDown={handleKeydown}
                            aria-label="Search input"
                            ref={inputRef}
                            aria-expanded={open}
                            aria-controls="suggestions-list"
                            aria-autocomplete="list"
                            size="small"
                            prefix={
                                <div className="flex items-center justify-center size-4 ml-[2px] mr-px">
                                    <IconSearch className="size-4" />
                                </div>
                            }
                        />
                    </PopoverPrimitiveTrigger>
                    <PopoverPrimitiveContent onOpenAutoFocus={e => e.preventDefault()} className='primitive-menu-content w-[var(--radix-popover-trigger-width)] max-w-none'>
                        <ListBox ref={listBoxRef} className="flex flex-col gap-px p-1">
                            {suggestions.map((item) => (
                                <ListBox.Item asChild key={item}>
                                    <ButtonPrimitive 
                                        onClick={() => handleSuggestionClick(item)}
                                        // tabIndex={0}
                                        // onKeyDown={(e) => handleButtonKeyDown(e, index)}
                                        // role="option"
                                        // aria-selected={false}
                                        menuItem
                                        >
                                        {item}
                                    </ButtonPrimitive>
                                </ListBox.Item>
                            ))}
                        </ListBox>
                    </PopoverPrimitiveContent>
                </PopoverPrimitive>
        );
    },
);
